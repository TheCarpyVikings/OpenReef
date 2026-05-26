'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import Hls from 'hls.js';
import { Camera, RefreshCw } from 'lucide-react';
import { apiFetch, withIngressPath } from '@/lib/api-fetch';
import styles from './live.module.css';

const DEFAULT_ENTITY_ID = 'camera.reef_tank';

export default function ReefTankLivePage() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [streamError, setStreamError] = useState(false);
  const [streamKey, setStreamKey] = useState(0);

  const entityId = useMemo(() => {
    if (typeof window === 'undefined') return DEFAULT_ENTITY_ID;
    const url = new URL(window.location.href);
    return url.searchParams.get('entity') || DEFAULT_ENTITY_ID;
  }, []);

  useEffect(() => {
    let cancelled = false;

    if (hlsRef.current) {
      hlsRef.current.destroy();
      hlsRef.current = null;
    }

    setStreamError(false);
    setIsLoading(true);

    async function startStream() {
      try {
        const video = videoRef.current;
        if (!video) return;

        const res = await apiFetch(`/api/camera/hls?entity=${encodeURIComponent(entityId)}`, {
          cache: 'no-store',
        });
        if (!res.ok) {
          throw new Error(`Live stream bootstrap failed: ${res.status}`);
        }

        const { token } = await res.json();
        if (cancelled) return;

        const hlsUrl = withIngressPath(`/api/camera/hls/${token}/master_playlist.m3u8`);

        if (Hls.isSupported()) {
          const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: true,
          });
          hlsRef.current = hls;

          hls.on(Hls.Events.MANIFEST_PARSED, () => {
            if (!cancelled) {
              setIsLoading(false);
              video.play().catch(() => {});
            }
          });

          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (data.fatal && !cancelled) {
              setStreamError(true);
              setIsLoading(false);
              hls.destroy();
              hlsRef.current = null;
            }
          });

          hls.loadSource(hlsUrl);
          hls.attachMedia(video);
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
          video.src = hlsUrl;
          setIsLoading(false);
          video.play().catch(() => {});
        } else {
          throw new Error('This browser does not support HLS playback.');
        }
      } catch {
        if (!cancelled) {
          setStreamError(true);
          setIsLoading(false);
        }
      }
    }

    startStream();

    return () => {
      cancelled = true;
      if (hlsRef.current) {
        hlsRef.current.destroy();
        hlsRef.current = null;
      }
    };
  }, [entityId, streamKey]);

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <section className={styles.header}>
          <div>
            <div className={styles.eyebrow}>
              <Camera size={16} />
              OpenReef Live
            </div>
            <h1 className={styles.title}>OpenReef Live View</h1>
            <p className={styles.subtitle}>
              A direct live look into the reef tank, streamed through Home Assistant and delivered over your private Tailscale network.
            </p>
          </div>

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.button}
              onClick={() => {
                setStreamError(false);
                setIsLoading(true);
                setStreamKey((value) => value + 1);
              }}
            >
              <RefreshCw size={16} style={{ marginRight: 8 }} />
              Reconnect Stream
            </button>
            <Link href="/" className={styles.button}>
              Open Dashboard
            </Link>
          </div>
        </section>

        <section className={styles.frame}>
          <video
            ref={videoRef}
            className={styles.video}
            muted
            playsInline
            controls
            autoPlay
          />

          {isLoading && !streamError && (
            <div className={styles.overlay}>
              <div className={styles.spinner} />
              <h2>Connecting to the reef camera...</h2>
              <p>The stream can take a few seconds to warm up while Home Assistant starts the live HLS session.</p>
            </div>
          )}

          {streamError && (
            <div className={styles.overlay}>
              <h2>Live stream unavailable</h2>
              <p>
                The camera stream did not start cleanly. Tap reconnect to try again. If it keeps failing,
                Lagertha can still send you a fresh photo or recording.
              </p>
              <button
                type="button"
                className={styles.button}
                onClick={() => {
                  setStreamError(false);
                  setIsLoading(true);
                  setStreamKey((value) => value + 1);
                }}
              >
                <RefreshCw size={16} style={{ marginRight: 8 }} />
                Retry Live View
              </button>
            </div>
          )}
        </section>

        <section className={styles.meta}>
          <span>
            Camera entity: <strong>{entityId}</strong>
          </span>
          <span>
            Access mode: <strong>Tailscale private link</strong>
          </span>
        </section>
      </div>
    </main>
  );
}
