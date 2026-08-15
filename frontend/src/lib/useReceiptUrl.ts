import { useEffect, useState } from 'react';

import { fetchReceiptBlobUrl } from './api';

/**
 * Load an authenticated receipt image as an object URL.
 * The URL is revoked on unmount, and on a race the late arrival is revoked too,
 * so switching between belegs quickly cannot leak blobs.
 */
export function useReceiptUrl(receiptId: string, thumb = false): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let created: string | null = null;

    fetchReceiptBlobUrl(receiptId, thumb)
      .then((objectUrl) => {
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        created = objectUrl;
        setUrl(objectUrl);
      })
      .catch(() => setUrl(null));

    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
      setUrl(null);
    };
  }, [receiptId, thumb]);

  return url;
}
