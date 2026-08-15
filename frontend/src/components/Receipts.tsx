import { useEffect, useState } from 'react';

import { Receipt } from '../lib/api';
import { useReceiptUrl } from '../lib/useReceiptUrl';

function Thumb({ receipt, onOpen }: { receipt: Receipt; onOpen: () => void }) {
  const url = useReceiptUrl(receipt.id, true);
  return (
    <button type="button" className="thumb" onClick={onOpen} aria-label="Kassenzettel ansehen">
      {url ? <img src={url} alt="" /> : null}
    </button>
  );
}

function Lightbox({ receiptId, onClose }: { receiptId: string; onClose: () => void }) {
  const url = useReceiptUrl(receiptId, false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="lightbox" onClick={onClose} role="dialog" aria-modal="true">
      {url ? <img src={url} alt="Kassenzettel" /> : <span style={{ color: '#fff' }}>Lädt…</span>}
    </div>
  );
}

interface Props {
  receipts: Receipt[];
  onUpload: (file: File) => void;
  onDelete: (receiptId: string) => void;
  canDelete: (receipt: Receipt) => boolean;
  uploading?: boolean;
  disabled?: boolean;
}

export default function Receipts({
  receipts,
  onUpload,
  onDelete,
  canDelete,
  uploading,
  disabled,
}: Props) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <>
      <div className="thumbs">
        {receipts.map((receipt) => (
          <div key={receipt.id} style={{ position: 'relative' }}>
            <Thumb receipt={receipt} onOpen={() => setOpen(receipt.id)} />
            {canDelete(receipt) && (
              <button
                type="button"
                className="icon-btn"
                onClick={() => onDelete(receipt.id)}
                aria-label="Kassenzettel löschen"
                style={{ position: 'absolute', top: -6, right: -6, width: 24, height: 24, fontSize: 13 }}
              >
                ×
              </button>
            )}
          </div>
        ))}

        {!disabled && (
          <label className="thumb add">
            <span className="plus" aria-hidden="true">
              {uploading ? '…' : '+'}
            </span>
            {uploading ? 'Lädt' : 'Beleg'}
            <input
              type="file"
              // `capture` opens the camera straight away on a phone.
              accept="image/*"
              capture="environment"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onUpload(file);
                e.target.value = '';
              }}
            />
          </label>
        )}
      </div>

      {open && <Lightbox receiptId={open} onClose={() => setOpen(null)} />}
    </>
  );
}
