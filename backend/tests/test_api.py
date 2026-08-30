"""End-to-end API tests against an in-memory SQLite database.

The production database is PostgreSQL; SQLite keeps the tests runnable without a
container. UUID and JSON usage here is portable across both.
"""

import io
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import CHAR, TypeDecorator


class SqliteUUID(TypeDecorator):
    """Store UUIDs as text so the PostgreSQL models load under SQLite."""

    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else str(value)

    def process_result_value(self, value, dialect):
        return None if value is None else uuid.UUID(value)


@pytest.fixture(scope="session", autouse=True)
def _patch_uuid_type():
    PGUUID.load_dialect_impl = lambda self, dialect: (  # type: ignore[method-assign]
        dialect.type_descriptor(SqliteUUID()) if dialect.name == "sqlite" else dialect.type_descriptor(self)
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import database, main, rate_limit
    from app.config import settings

    settings.upload_dir = tmp_path / "receipts"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    # The app refuses to start on the built-in key, so give the tests a real one.
    settings.jwt_secret = "test-secret-that-is-long-enough-for-hs256-abc"

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    database.Base.metadata.create_all(bind=engine)

    # main imported `engine` by value, so both references need redirecting or the
    # startup hook and the health check would dial the real PostgreSQL host.
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(main, "engine", engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[database.get_db] = override_db
    rate_limit._ATTEMPTS.clear()

    with TestClient(main.app) as c:
        yield c

    main.app.dependency_overrides.clear()


def make_group(client, name="Mallorca 2026", password="sommer2026!", admin="Leo"):
    response = client.post(
        "/api/auth/groups",
        json={"name": name, "password": password, "currency": "EUR", "admin_name": admin},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_header(session):
    return {"Authorization": f"Bearer {session['access_token']}"}


def photo_bytes(size=(800, 1200), fmt="JPEG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, (240, 240, 240)).save(buffer, format=fmt)
    return buffer.getvalue()


class TestAuth:
    def test_create_group_returns_admin_session(self, client):
        session = make_group(client)
        assert session["member"]["is_admin"] is True
        assert session["member"]["display_name"] == "Leo"
        assert session["device_id"]

    def test_friend_joins_with_group_password(self, client):
        group = make_group(client)
        response = client.post(
            "/api/auth/login",
            json={
                "group_slug": group["group"]["slug"],
                "password": "sommer2026!",
                "display_name": "Anna",
            },
        )
        assert response.status_code == 200
        assert response.json()["member"]["is_admin"] is False

    def test_wrong_password_is_rejected(self, client):
        group = make_group(client)
        response = client.post(
            "/api/auth/login",
            json={
                "group_slug": group["group"]["slug"],
                "password": "falsch",
                "display_name": "Anna",
            },
        )
        assert response.status_code == 401

    def test_name_is_locked_to_the_first_device(self, client):
        group = make_group(client)
        slug = group["group"]["slug"]
        first = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        ).json()

        # A different phone with the correct group password still cannot be "Anna".
        stolen = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        )
        assert stolen.status_code == 409

        # Anna's own phone gets back in by presenting its device id.
        again = client.post(
            "/api/auth/login",
            json={
                "group_slug": slug,
                "password": "sommer2026!",
                "display_name": "Anna",
                "device_id": first["device_id"],
            },
        )
        assert again.status_code == 200

    def test_names_are_case_insensitive(self, client):
        group = make_group(client)
        slug = group["group"]["slug"]
        client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        )
        clash = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "anna"},
        )
        assert clash.status_code == 409

    def test_login_is_rate_limited(self, client):
        group = make_group(client)
        slug = group["group"]["slug"]
        codes = [
            client.post(
                "/api/auth/login",
                json={"group_slug": slug, "password": f"wrong{i}", "display_name": "Anna"},
            ).status_code
            for i in range(12)
        ]
        assert 429 in codes

    def test_endpoints_require_a_token(self, client):
        assert client.get("/api/expenses").status_code == 401

    def test_tampered_token_is_rejected(self, client):
        session = make_group(client)
        bad = {"Authorization": f"Bearer {session['access_token'][:-3]}xyz"}
        assert client.get("/api/expenses", headers=bad).status_code == 401


class TestExpenses:
    @pytest.fixture
    def trip(self, client):
        admin = make_group(client)
        slug = admin["group"]["slug"]
        anna = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        ).json()
        return {"admin": admin, "anna": anna}

    def test_equal_split_creates_matching_shares(self, client, trip):
        admin = trip["admin"]
        members = client.get("/api/members", headers=auth_header(admin)).json()
        ids = [m["id"] for m in members]

        response = client.post(
            "/api/expenses",
            headers=auth_header(admin),
            json={
                "description": "Abendessen",
                "amount_cents": 10000,
                "payer_id": admin["member"]["id"],
                "expense_date": str(date.today()),
                "category": "food",
                "split_type": "equal",
                "participant_ids": ids,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert sum(s["amount_cents"] for s in body["shares"]) == 10000

    def test_exact_split_must_add_up(self, client, trip):
        admin = trip["admin"]
        members = client.get("/api/members", headers=auth_header(admin)).json()
        response = client.post(
            "/api/expenses",
            headers=auth_header(admin),
            json={
                "description": "Taxi",
                "amount_cents": 5000,
                "payer_id": admin["member"]["id"],
                "expense_date": str(date.today()),
                "split_type": "exact",
                "shares": [
                    {"member_id": members[0]["id"], "value": 2000},
                    {"member_id": members[1]["id"], "value": 2000},
                ],
            },
        )
        assert response.status_code == 400
        assert "50.00" in response.json()["detail"]

    def test_cannot_reference_a_member_of_another_group(self, client, trip):
        other = make_group(client, name="Andere Reise", admin="Fremd")
        response = client.post(
            "/api/expenses",
            headers=auth_header(trip["admin"]),
            json={
                "description": "Fremd",
                "amount_cents": 1000,
                "payer_id": other["member"]["id"],
                "expense_date": str(date.today()),
                "split_type": "equal",
                "participant_ids": [other["member"]["id"]],
            },
        )
        assert response.status_code == 400

    def test_expenses_are_scoped_to_the_group(self, client, trip):
        admin = trip["admin"]
        client.post(
            "/api/expenses",
            headers=auth_header(admin),
            json={
                "description": "Geheim",
                "amount_cents": 1000,
                "payer_id": admin["member"]["id"],
                "expense_date": str(date.today()),
                "split_type": "equal",
                "participant_ids": [admin["member"]["id"]],
            },
        )
        other = make_group(client, name="Andere Reise", admin="Fremd")
        visible = client.get("/api/expenses", headers=auth_header(other)).json()
        assert visible == []

    def test_only_author_or_admin_may_delete(self, client, trip):
        anna = trip["anna"]
        created = client.post(
            "/api/expenses",
            headers=auth_header(anna),
            json={
                "description": "Eis",
                "amount_cents": 600,
                "payer_id": anna["member"]["id"],
                "expense_date": str(date.today()),
                "split_type": "equal",
                "participant_ids": [anna["member"]["id"]],
            },
        ).json()

        # The admin may clean up anyone's entry.
        assert (
            client.delete(
                f"/api/expenses/{created['id']}", headers=auth_header(trip["admin"])
            ).status_code
            == 204
        )

    def test_non_author_non_admin_is_refused(self, client, trip):
        admin, anna = trip["admin"], trip["anna"]
        created = client.post(
            "/api/expenses",
            headers=auth_header(admin),
            json={
                "description": "Hotel",
                "amount_cents": 20000,
                "payer_id": admin["member"]["id"],
                "expense_date": str(date.today()),
                "split_type": "equal",
                "participant_ids": [admin["member"]["id"]],
            },
        ).json()
        response = client.delete(f"/api/expenses/{created['id']}", headers=auth_header(anna))
        assert response.status_code == 403

    def test_rejects_zero_amount(self, client, trip):
        admin = trip["admin"]
        response = client.post(
            "/api/expenses",
            headers=auth_header(admin),
            json={
                "description": "Nichts",
                "amount_cents": 0,
                "payer_id": admin["member"]["id"],
                "expense_date": str(date.today()),
                "split_type": "equal",
                "participant_ids": [admin["member"]["id"]],
            },
        )
        assert response.status_code == 422


class TestBalances:
    def test_balance_reflects_who_paid(self, client):
        admin = make_group(client)
        slug = admin["group"]["slug"]
        client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        )
        members = client.get("/api/members", headers=auth_header(admin)).json()
        ids = [m["id"] for m in members]

        client.post(
            "/api/expenses",
            headers=auth_header(admin),
            json={
                "description": "Ferienwohnung",
                "amount_cents": 40000,
                "payer_id": admin["member"]["id"],
                "expense_date": str(date.today()),
                "split_type": "equal",
                "participant_ids": ids,
            },
        )

        summary = client.get("/api/balances", headers=auth_header(admin)).json()
        assert summary["total_spent_cents"] == 40000
        assert sum(b["net_cents"] for b in summary["balances"]) == 0
        assert len(summary["suggested_transfers"]) == 1
        assert summary["suggested_transfers"][0]["amount_cents"] == 20000

    def test_settlement_zeroes_the_balance(self, client):
        admin = make_group(client)
        slug = admin["group"]["slug"]
        client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        )
        members = client.get("/api/members", headers=auth_header(admin)).json()
        anna = next(m for m in members if m["display_name"] == "Anna")

        client.post(
            "/api/expenses",
            headers=auth_header(admin),
            json={
                "description": "Tanken",
                "amount_cents": 10000,
                "payer_id": admin["member"]["id"],
                "expense_date": str(date.today()),
                "split_type": "equal",
                "participant_ids": [m["id"] for m in members],
            },
        )
        client.post(
            "/api/settlements",
            headers=auth_header(admin),
            json={
                "from_member_id": anna["id"],
                "to_member_id": admin["member"]["id"],
                "amount_cents": 5000,
            },
        )

        summary = client.get("/api/balances", headers=auth_header(admin)).json()
        assert all(b["net_cents"] == 0 for b in summary["balances"])
        assert summary["suggested_transfers"] == []


class TestReceipts:
    @pytest.fixture
    def expense(self, client):
        admin = make_group(client)
        created = client.post(
            "/api/expenses",
            headers=auth_header(admin),
            json={
                "description": "Supermarkt",
                "amount_cents": 4523,
                "payer_id": admin["member"]["id"],
                "expense_date": str(date.today()),
                "category": "groceries",
                "split_type": "equal",
                "participant_ids": [admin["member"]["id"]],
            },
        ).json()
        return admin, created

    def test_upload_and_fetch(self, client, expense):
        admin, created = expense
        response = client.post(
            f"/api/expenses/{created['id']}/receipts",
            headers=auth_header(admin),
            files={"file": ("kassenzettel.jpg", photo_bytes(), "image/jpeg")},
        )
        assert response.status_code == 201, response.text
        receipt_id = response.json()["id"]

        image = client.get(f"/api/receipts/{receipt_id}", headers=auth_header(admin))
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"

        thumb = client.get(f"/api/receipts/{receipt_id}?thumb=true", headers=auth_header(admin))
        assert thumb.status_code == 200
        assert len(thumb.content) < len(image.content)

    def test_large_image_is_downscaled(self, client, expense):
        admin, created = expense
        response = client.post(
            f"/api/expenses/{created['id']}/receipts",
            headers=auth_header(admin),
            files={"file": ("gross.jpg", photo_bytes((4000, 3000)), "image/jpeg")},
        )
        assert response.status_code == 201
        image = client.get(f"/api/receipts/{response.json()['id']}", headers=auth_header(admin))
        with Image.open(io.BytesIO(image.content)) as stored:
            assert max(stored.size) <= 2000

    def test_non_image_is_rejected(self, client, expense):
        admin, created = expense
        response = client.post(
            f"/api/expenses/{created['id']}/receipts",
            headers=auth_header(admin),
            files={"file": ("virus.jpg", b"MZ\x90\x00 not an image", "image/jpeg")},
        )
        assert response.status_code == 400

    def test_wrong_content_type_is_rejected(self, client, expense):
        admin, created = expense
        response = client.post(
            f"/api/expenses/{created['id']}/receipts",
            headers=auth_header(admin),
            files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert response.status_code == 415

    def test_receipt_is_not_visible_to_another_group(self, client, expense):
        admin, created = expense
        receipt_id = client.post(
            f"/api/expenses/{created['id']}/receipts",
            headers=auth_header(admin),
            files={"file": ("beleg.jpg", photo_bytes(), "image/jpeg")},
        ).json()["id"]

        other = make_group(client, name="Andere Reise", admin="Fremd")
        response = client.get(f"/api/receipts/{receipt_id}", headers=auth_header(other))
        assert response.status_code == 404

    def test_deleting_the_expense_removes_the_file(self, client, expense):
        from app.storage import resolve_path

        admin, created = expense
        client.post(
            f"/api/expenses/{created['id']}/receipts",
            headers=auth_header(admin),
            files={"file": ("beleg.jpg", photo_bytes(), "image/jpeg")},
        )
        detail = client.get(f"/api/expenses/{created['id']}", headers=auth_header(admin)).json()
        assert len(detail["receipts"]) == 1

        client.delete(f"/api/expenses/{created['id']}", headers=auth_header(admin))
        assert not list(resolve_path(".").rglob("*.jpg"))


class TestAdmin:
    def test_admin_can_release_a_lost_phone(self, client):
        admin = make_group(client)
        slug = admin["group"]["slug"]
        client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        )
        members = client.get("/api/members", headers=auth_header(admin)).json()
        anna = next(m for m in members if m["display_name"] == "Anna")

        assert (
            client.post(
                f"/api/admin/members/{anna['id']}/release", headers=auth_header(admin)
            ).status_code
            == 204
        )

        # A new phone can now claim the name again.
        response = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        )
        assert response.status_code == 200

    def test_rebinding_keeps_the_members_expenses_and_balance(self, client):
        """A new phone reclaiming a released name inherits the same member record.

        This is the lost-phone recovery path: nothing that was already booked may
        move, disappear, or turn into a second person with the same name.
        """
        admin = make_group(client)
        slug = admin["group"]["slug"]
        anna = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        ).json()
        anna_id = anna["member"]["id"]

        client.post(
            "/api/expenses",
            headers=auth_header(anna),
            json={
                "description": "Mietwagen",
                "amount_cents": 24000,
                "payer_id": anna_id,
                "expense_date": str(date.today()),
                "split_type": "equal",
                "participant_ids": [anna_id, admin["member"]["id"]],
            },
        )
        before = client.get("/api/balances", headers=auth_header(admin)).json()

        # Anna's phone is gone: the admin frees the name, a new phone claims it.
        client.post(f"/api/admin/members/{anna_id}/release", headers=auth_header(admin))
        new_phone = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        )
        assert new_phone.status_code == 200
        reclaimed = new_phone.json()

        # Same member id -- not a second "Anna" alongside the old one.
        assert reclaimed["member"]["id"] == anna_id
        assert len(client.get("/api/members", headers=auth_header(admin)).json()) == 2

        after = client.get("/api/balances", headers=auth_header(admin)).json()
        assert after["balances"] == before["balances"]
        assert after["total_spent_cents"] == 24000

        # And the new phone still owns what the old one entered.
        expenses = client.get("/api/expenses", headers=auth_header(reclaimed)).json()
        assert expenses[0]["created_by_id"] == anna_id
        assert (
            client.delete(
                f"/api/expenses/{expenses[0]['id']}", headers=auth_header(reclaimed)
            ).status_code
            == 204
        )

    def test_same_phone_returns_without_admin_help(self, client):
        """An expired session on the *same* phone needs no admin: the device id proves it."""
        admin = make_group(client)
        slug = admin["group"]["slug"]
        anna = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        ).json()

        again = client.post(
            "/api/auth/login",
            json={
                "group_slug": slug,
                "password": "sommer2026!",
                "display_name": "Anna",
                "device_id": anna["device_id"],
            },
        )
        assert again.status_code == 200
        assert again.json()["member"]["id"] == anna["member"]["id"]

    def test_non_admin_cannot_release(self, client):
        admin = make_group(client)
        slug = admin["group"]["slug"]
        anna = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        ).json()
        response = client.post(
            f"/api/admin/members/{anna['member']['id']}/release", headers=auth_header(anna)
        )
        assert response.status_code == 403

    def test_released_device_loses_its_session(self, client):
        admin = make_group(client)
        slug = admin["group"]["slug"]
        anna = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        ).json()
        client.post(
            f"/api/admin/members/{anna['member']['id']}/release", headers=auth_header(admin)
        )
        assert client.get("/api/expenses", headers=auth_header(anna)).status_code == 401

    def test_password_rotation_blocks_the_old_password(self, client):
        admin = make_group(client)
        slug = admin["group"]["slug"]
        client.post(
            "/api/admin/password", headers=auth_header(admin), json={"new_password": "neu-2026!"}
        )
        old = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Neu"},
        )
        assert old.status_code == 401


class TestRecoveryKey:
    """The emergency key: the way back in when the admin's own phone is gone."""

    def test_key_is_issued_once_at_creation(self, client):
        session = make_group(client)
        key = session["recovery_key"]
        assert key and len(key.replace("-", "")) == 16

        # It is never handed out again, not even to the admin's own session.
        assert client.get("/api/auth/me", headers=auth_header(session)).json()[
            "recovery_key"
        ] is None

    def test_admin_locked_out_recovers_name_and_admin_rights(self, client):
        admin = make_group(client)
        slug, key = admin["group"]["slug"], admin["recovery_key"]
        admin_id = admin["member"]["id"]

        client.post(
            "/api/expenses",
            headers=auth_header(admin),
            json={
                "description": "Fähre",
                "amount_cents": 8000,
                "payer_id": admin_id,
                "expense_date": str(date.today()),
                "split_type": "equal",
                "participant_ids": [admin_id],
            },
        )

        # Leo's phone is gone: no device id, and nobody else can release his name.
        blocked = client.post(
            "/api/auth/login",
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Leo"},
        )
        assert blocked.status_code == 409

        recovered = client.post(
            "/api/auth/login",
            json={
                "group_slug": slug,
                "password": "sommer2026!",
                "display_name": "Leo",
                "recovery_key": key,
            },
        )
        assert recovered.status_code == 200
        body = recovered.json()
        assert body["member"]["id"] == admin_id
        assert body["member"]["is_admin"] is True

        # The trip is intact and the new phone can act as admin.
        assert client.get("/api/balances", headers=auth_header(body)).json()[
            "total_spent_cents"
        ] == 8000
        assert (
            client.post("/api/admin/password", headers=auth_header(body), json={"new_password": "neu-2026!"}).status_code
            == 204
        )

    def test_used_key_cannot_be_replayed(self, client):
        admin = make_group(client)
        slug, key = admin["group"]["slug"], admin["recovery_key"]

        first = client.post(
            "/api/auth/login",
            json={
                "group_slug": slug,
                "password": "sommer2026!",
                "display_name": "Leo",
                "recovery_key": key,
            },
        ).json()
        # A fresh key is handed out in the same response...
        assert first["recovery_key"] and first["recovery_key"] != key

        # ...and the old one is dead.
        replay = client.post(
            "/api/auth/login",
            json={
                "group_slug": slug,
                "password": "sommer2026!",
                "display_name": "Leo",
                "recovery_key": key,
            },
        )
        assert replay.status_code == 401

        # The newly issued one works.
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "group_slug": slug,
                    "password": "sommer2026!",
                    "display_name": "Leo",
                    "recovery_key": first["recovery_key"],
                },
            ).status_code
            == 200
        )

    def test_key_is_accepted_in_any_writing(self, client):
        admin = make_group(client)
        slug, key = admin["group"]["slug"], admin["recovery_key"]
        sloppy = f"  {key.replace('-', '').lower()}  "

        response = client.post(
            "/api/auth/login",
            json={
                "group_slug": slug,
                "password": "sommer2026!",
                "display_name": "Leo",
                "recovery_key": sloppy,
            },
        )
        assert response.status_code == 200

    def test_key_alone_is_not_enough_without_the_group_password(self, client):
        admin = make_group(client)
        response = client.post(
            "/api/auth/login",
            json={
                "group_slug": admin["group"]["slug"],
                "password": "falsch",
                "display_name": "Leo",
                "recovery_key": admin["recovery_key"],
            },
        )
        assert response.status_code == 401

    def test_key_of_another_trip_does_not_work(self, client):
        admin = make_group(client)
        other = make_group(client, name="Andere Reise", admin="Fremd")
        response = client.post(
            "/api/auth/login",
            json={
                "group_slug": admin["group"]["slug"],
                "password": "sommer2026!",
                "display_name": "Leo",
                "recovery_key": other["recovery_key"],
            },
        )
        assert response.status_code == 401

    def test_key_cannot_invent_a_new_member(self, client):
        admin = make_group(client)
        response = client.post(
            "/api/auth/login",
            json={
                "group_slug": admin["group"]["slug"],
                "password": "sommer2026!",
                "display_name": "Wildfremd",
                "recovery_key": admin["recovery_key"],
            },
        )
        assert response.status_code == 404

    def test_recovery_attempts_are_tightly_rate_limited(self, client):
        admin = make_group(client)
        slug = admin["group"]["slug"]
        codes = [
            client.post(
                "/api/auth/login",
                json={
                    "group_slug": slug,
                    "password": "sommer2026!",
                    "display_name": "Leo",
                    "recovery_key": "AAAA-BBBB-CCCC-DDDD",
                },
            ).status_code
            for _ in range(7)
        ]
        # Far stricter than the 10 ordinary password attempts.
        assert codes.count(429) >= 1
        assert codes.index(429) <= 5

    def test_admin_can_issue_a_replacement_key(self, client):
        admin = make_group(client)
        slug, old = admin["group"]["slug"], admin["recovery_key"]

        fresh = client.post("/api/admin/recovery-key", headers=auth_header(admin))
        assert fresh.status_code == 200
        new_key = fresh.json()["recovery_key"]
        assert new_key != old

        assert (
            client.post(
                "/api/auth/login",
                json={
                    "group_slug": slug,
                    "password": "sommer2026!",
                    "display_name": "Leo",
                    "recovery_key": old,
                },
            ).status_code
            == 401
        )

    def test_only_admin_may_issue_a_replacement_key(self, client):
        admin = make_group(client)
        anna = client.post(
            "/api/auth/login",
            json={
                "group_slug": admin["group"]["slug"],
                "password": "sommer2026!",
                "display_name": "Anna",
            },
        ).json()
        assert client.post("/api/admin/recovery-key", headers=auth_header(anna)).status_code == 403

    def test_recovery_is_recorded_in_the_audit_log(self, client):
        admin = make_group(client)
        recovered = client.post(
            "/api/auth/login",
            json={
                "group_slug": admin["group"]["slug"],
                "password": "sommer2026!",
                "display_name": "Leo",
                "recovery_key": admin["recovery_key"],
            },
        ).json()

        activity = client.get("/api/activity", headers=auth_header(recovered)).json()
        assert any(entry["action"] == "member.recover" for entry in activity)


class TestHardening:
    def test_startup_refuses_the_built_in_signing_key(self):
        from app.config import Settings, settings as live

        before = live.jwt_secret
        try:
            live.jwt_secret = Settings.model_fields["jwt_secret"].default
            problems = live.validate_secrets()
            assert problems and "JWT_SECRET" in problems[0]
        finally:
            live.jwt_secret = before

    def test_startup_refuses_a_short_signing_key(self):
        from app.config import settings as live

        before = live.jwt_secret
        try:
            live.jwt_secret = "kurz"
            assert live.validate_secrets()
        finally:
            live.jwt_secret = before

    def test_a_strong_key_passes(self):
        from app.config import settings as live

        assert live.validate_secrets() == []

    def test_api_schema_is_not_public(self, client):
        # The docs map every endpoint; they stay off unless explicitly enabled.
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/docs").status_code == 404

    def test_client_ip_prefers_the_proxy_header(self, client):
        from fastapi import Request

        from app.deps import client_ip

        scope = {
            "type": "http",
            "headers": [(b"x-real-ip", b"203.0.113.9")],
            "client": ("172.18.0.4", 1234),
        }
        assert client_ip(Request(scope)) == "203.0.113.9"

    def test_client_ip_falls_back_to_the_socket(self, client):
        from fastapi import Request

        from app.deps import client_ip

        scope = {"type": "http", "headers": [], "client": ("198.51.100.7", 1234)}
        assert client_ip(Request(scope)) == "198.51.100.7"

    def test_rate_limit_is_per_address_not_global(self, client):
        """One noisy visitor must not lock the rest of the group out."""
        group = make_group(client)
        slug = group["group"]["slug"]

        for _ in range(12):
            client.post(
                "/api/auth/login",
                headers={"X-Real-IP": "203.0.113.1"},
                json={"group_slug": slug, "password": "falsch", "display_name": "Anna"},
            )

        blocked = client.post(
            "/api/auth/login",
            headers={"X-Real-IP": "203.0.113.1"},
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Anna"},
        )
        assert blocked.status_code == 429

        # A different visitor is unaffected.
        other = client.post(
            "/api/auth/login",
            headers={"X-Real-IP": "203.0.113.2"},
            json={"group_slug": slug, "password": "sommer2026!", "display_name": "Ben"},
        )
        assert other.status_code == 200


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"
