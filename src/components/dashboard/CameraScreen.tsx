'use client';

import React, { useState, useRef, useCallback, useEffect } from 'react';
import Hls from 'hls.js';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { apiFetch, withIngressPath } from '@/lib/api-fetch';
import { Camera, Maximize2, Minimize2, Download, RefreshCw, VideoOff, Settings } from 'lucide-react';

interface CameraScreenProps {
    setActiveTab?: (tab: string) => void;
}

export const CameraScreen: React.FC<CameraScreenProps> = ({ setActiveTab }) => {
    const { settings } = useSettings();
    const [activeCamId, setActiveCamId] = useState<string>(settings.camera.cameras[0]?.id || '');
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [streamError, setStreamError] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const videoRef = useRef<HTMLVideoElement>(null);
    const hlsRef = useRef<Hls | null>(null);
    const [streamKey, setStreamKey] = useState(0);

    const cameras = settings.camera.cameras;
    const activeCam = cameras.find(c => c.id === activeCamId) || cameras[0];

    // Build a snapshot URL — proxied through Next.js server.
    const getSnapshotUrl = useCallback((entityId: string) => {
        if (!entityId) return '';
        return withIngressPath(`/api/camera/snapshot?entity=${encodeURIComponent(entityId)}`);
    }, []);

    // Start HLS stream via HA's WebSocket camera/stream API.
    // This is the same mechanism HA Lovelace uses — full framerate, through HA.
    useEffect(() => {
        if (!activeCam) return;

        const video = videoRef.current;
        if (!video) return;
        const entityId = activeCam.entityId;

        let cancelled = false;

        // Clean up any previous HLS instance.
        if (hlsRef.current) {
            hlsRef.current.destroy();
            hlsRef.current = null;
        }

        setStreamError(false);
        setIsLoading(true);

        async function startHLS(videoElement: HTMLVideoElement) {
            try {
                // 1. Request HLS token from our server-side proxy.
                const res = await apiFetch(
                    `/api/camera/hls?entity=${encodeURIComponent(entityId)}`,
                );
                if (!res.ok) throw new Error(`HLS start failed: ${res.status}`);
                const { token } = await res.json();
                if (cancelled) return;

                const hlsUrl = withIngressPath(`/api/camera/hls/${token}/master_playlist.m3u8`);

                // 2. Attach HLS.js (or use native HLS on Safari).
                if (Hls.isSupported()) {
                    const hls = new Hls({
                        enableWorker: true,
                        lowLatencyMode: true,
                    });
                    hlsRef.current = hls;

                    hls.on(Hls.Events.MANIFEST_PARSED, () => {
                        if (!cancelled) {
                            videoElement.play().catch(() => {});
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
                    hls.attachMedia(videoElement);
                } else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
                    // Native HLS (Safari).
                    videoElement.src = hlsUrl;
                    videoElement.play().catch(() => {});
                } else {
                    setStreamError(true);
                    setIsLoading(false);
                }
            } catch {
                if (!cancelled) {
                    setStreamError(true);
                    setIsLoading(false);
                }
            }
        }

        void startHLS(video);

        return () => {
            cancelled = true;
            if (hlsRef.current) {
                hlsRef.current.destroy();
                hlsRef.current = null;
            }
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeCam?.entityId, streamKey]);

    // Fullscreen toggle
    const toggleFullscreen = useCallback(() => {
        if (!containerRef.current) return;
        if (!document.fullscreenElement) {
            containerRef.current.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => { });
        } else {
            document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => { });
        }
    }, []);

    useEffect(() => {
        const handleFSChange = () => {
            setIsFullscreen(!!document.fullscreenElement);
        };
        document.addEventListener('fullscreenchange', handleFSChange);
        return () => document.removeEventListener('fullscreenchange', handleFSChange);
    }, []);

    // Snapshot capture
    const takeSnapshot = useCallback(() => {
        if (!activeCam) return;
        const url = getSnapshotUrl(activeCam.entityId);
        setSnapshotUrl(url);

        // Auto-dismiss after 5 seconds
        setTimeout(() => setSnapshotUrl(null), 5000);

        // Also download it
        const a = document.createElement('a');
        a.href = url;
        a.download = `reef-snapshot-${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`;
        a.click();
    }, [activeCam, getSnapshotUrl]);

    // Refresh stream
    const refreshStream = useCallback(() => {
        setStreamError(false);
        setIsLoading(true);
        setStreamKey(prev => prev + 1);
    }, []);

    // Reset to first cam if active cam is removed
    useEffect(() => {
        if (cameras.length > 0 && !cameras.find(c => c.id === activeCamId)) {
            setActiveCamId(cameras[0].id);
        }
    }, [cameras, activeCamId]);

    // Empty state
    if (!settings.camera.enabled || cameras.length === 0) {
        return (
            <div className={styles.missionControl}>
                <div className={styles.card} style={{
                    textAlign: 'center',
                    padding: '4rem 2rem',
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px dashed #27272a',
                }}>
                    <VideoOff size={48} style={{ color: '#778da9', marginBottom: '1.5rem' }} />
                    <h3 style={{ color: '#e0e1dd', margin: '0 0 0.75rem 0', fontSize: '1.3rem' }}>
                        {!settings.camera.enabled ? 'Camera Disabled' : 'No Cameras Configured'}
                    </h3>
                    <p style={{ color: '#778da9', margin: '0 0 1.5rem 0', maxWidth: '400px', marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.6 }}>
                        {!settings.camera.enabled
                            ? 'Enable the camera feature in Settings → Camera to start viewing your reef live.'
                            : 'Add a camera entity from Home Assistant in Settings → Camera to start viewing your reef live.'}
                    </p>
                    {setActiveTab && (
                        <button
                            onClick={() => setActiveTab('settings')}
                            style={{
                                padding: '0.75rem 1.5rem',
                                background: 'var(--primary-color)',
                                color: '#fff',
                                border: 'none',
                                borderRadius: '8px',
                                cursor: 'pointer',
                                fontSize: '0.9rem',
                                fontWeight: 600,
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                            }}
                        >
                            <Settings size={18} /> Go to Camera Settings
                        </button>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div className={styles.missionControl} ref={containerRef} style={isFullscreen ? { background: '#000', padding: 0 } : undefined}>
            {/* Multi-camera tabs */}
            {cameras.length > 1 && (
                <div style={{
                    display: 'flex',
                    gap: '0.5rem',
                    marginBottom: '1rem',
                    flexWrap: 'wrap',
                }}>
                    {cameras.map(cam => (
                        <button
                            key={cam.id}
                            onClick={() => { setActiveCamId(cam.id); setStreamError(false); setIsLoading(true); }}
                            className={styles.tabItem}
                            style={{
                                padding: '0.5rem 1rem',
                                background: activeCamId === cam.id ? 'var(--primary-color)' : 'rgba(255,255,255,0.05)',
                                color: activeCamId === cam.id ? '#fff' : '#778da9',
                                border: activeCamId === cam.id ? 'none' : '1px solid rgba(255,255,255,0.1)',
                                borderRadius: '8px',
                                cursor: 'pointer',
                                fontSize: '0.85rem',
                                fontWeight: 600,
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                transition: 'all 0.2s ease',
                            }}
                        >
                            <Camera size={14} />
                            {cam.label}
                        </button>
                    ))}
                </div>
            )}

            {/* Stream container */}
            <div className={styles.card} style={{
                padding: 0,
                overflow: 'hidden',
                position: 'relative',
                borderRadius: isFullscreen ? 0 : '12px',
            }}>
                {/* Live indicator */}
                <div style={{
                    position: 'absolute',
                    top: '1rem',
                    left: '1rem',
                    zIndex: 10,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    background: 'rgba(0,0,0,0.6)',
                    backdropFilter: 'blur(8px)',
                    padding: '0.35rem 0.75rem',
                    borderRadius: '6px',
                }}>
                    <div className={styles.liveIndicator} />
                    <span style={{ color: '#fff', fontSize: '0.75rem', fontWeight: 700, letterSpacing: '0.05em' }}>LIVE</span>
                </div>

                {/* Camera label overlay */}
                <div style={{
                    position: 'absolute',
                    top: '1rem',
                    right: '1rem',
                    zIndex: 10,
                    background: 'rgba(0,0,0,0.6)',
                    backdropFilter: 'blur(8px)',
                    padding: '0.35rem 0.75rem',
                    borderRadius: '6px',
                    color: '#e0e1dd',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                }}>
                    {activeCam?.label || 'Camera'}
                </div>

                {/* Stream */}
                <div style={{
                    position: 'relative',
                    width: '100%',
                    paddingTop: '56.25%', // 16:9 aspect ratio
                    background: '#0a0a0a',
                }}>
                    {streamError ? (
                        <div style={{
                            position: 'absolute',
                            inset: 0,
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#778da9',
                            gap: '1rem',
                        }}>
                            <VideoOff size={48} style={{ opacity: 0.5 }} />
                            <p style={{ margin: 0, fontSize: '0.9rem' }}>Stream unavailable</p>
                            <p style={{ margin: 0, fontSize: '0.75rem', color: '#555', maxWidth: '300px', textAlign: 'center' }}>
                                Check that the camera entity <code style={{ color: '#00b4d8' }}>{activeCam?.entityId}</code> exists in Home Assistant and is streaming.
                            </p>
                            <button
                                onClick={refreshStream}
                                style={{
                                    padding: '0.5rem 1rem',
                                    background: 'rgba(255,255,255,0.05)',
                                    color: '#e0e1dd',
                                    border: '1px solid rgba(255,255,255,0.1)',
                                    borderRadius: '6px',
                                    cursor: 'pointer',
                                    fontSize: '0.8rem',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                }}
                            >
                                <RefreshCw size={14} /> Retry
                            </button>
                        </div>
                    ) : (
                        <>
                            {isLoading && (
                                <div style={{
                                    position: 'absolute',
                                    inset: 0,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    color: '#778da9',
                                    gap: '0.75rem',
                                }}>
                                    <RefreshCw size={20} className={styles.spin} />
                                    <span style={{ fontSize: '0.85rem' }}>Connecting to stream...</span>
                                </div>
                            )}
                            <video
                                ref={videoRef}
                                autoPlay
                                muted
                                playsInline
                                onPlaying={() => setIsLoading(false)}
                                onError={() => { setStreamError(true); setIsLoading(false); }}
                                style={{
                                    position: 'absolute',
                                    inset: 0,
                                    width: '100%',
                                    height: '100%',
                                    objectFit: 'contain',
                                    display: isLoading ? 'none' : 'block',
                                }}
                            />
                        </>
                    )}
                </div>
            </div>

            {/* Controls toolbar */}
            <div style={{
                display: 'flex',
                justifyContent: 'center',
                gap: '0.75rem',
                marginTop: '1rem',
                flexWrap: 'wrap',
            }}>
                {[
                    { icon: <Download size={16} />, label: 'Snapshot', onClick: takeSnapshot, disabled: streamError },
                    { icon: <RefreshCw size={16} />, label: 'Refresh', onClick: refreshStream },
                    { icon: isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />, label: isFullscreen ? 'Exit Fullscreen' : 'Fullscreen', onClick: toggleFullscreen },
                ].map((action, i) => (
                    <button
                        key={i}
                        onClick={action.onClick}
                        disabled={action.disabled}
                        style={{
                            padding: '0.6rem 1.2rem',
                            background: 'rgba(255,255,255,0.05)',
                            color: action.disabled ? '#555' : '#e0e1dd',
                            border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: '8px',
                            cursor: action.disabled ? 'not-allowed' : 'pointer',
                            fontSize: '0.8rem',
                            fontWeight: 600,
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            transition: 'all 0.2s ease',
                            opacity: action.disabled ? 0.4 : 1,
                        }}
                    >
                        {action.icon} {action.label}
                    </button>
                ))}
            </div>

            {/* Snapshot toast */}
            {snapshotUrl && (
                <div style={{
                    position: 'fixed',
                    bottom: '2rem',
                    right: '2rem',
                    background: 'rgba(16, 185, 129, 0.15)',
                    border: '1px solid rgba(16, 185, 129, 0.3)',
                    borderRadius: '10px',
                    padding: '0.75rem 1.25rem',
                    color: '#10b981',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    zIndex: 1000,
                    animation: 'fadeIn 0.3s ease',
                    backdropFilter: 'blur(12px)',
                }}>
                    <Camera size={16} /> Snapshot saved!
                </div>
            )}

            {/* Camera info card */}
            {activeCam && (
                <div className={styles.card} style={{
                    marginTop: '1rem',
                    padding: '1rem 1.5rem',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                    gap: '1rem',
                }}>
                    <div>
                        <div style={{ fontSize: '0.8rem', color: '#778da9', marginBottom: '0.25rem' }}>Entity</div>
                        <code style={{ color: '#00b4d8', fontSize: '0.85rem' }}>{activeCam.entityId}</code>
                    </div>
                    <div>
                        <div style={{ fontSize: '0.8rem', color: '#778da9', marginBottom: '0.25rem' }}>Stream Type</div>
                        <span style={{ color: '#e0e1dd', fontSize: '0.85rem', textTransform: 'uppercase', fontWeight: 600 }}>
                            HLS
                        </span>
                    </div>
                    <div>
                        <div style={{ fontSize: '0.8rem', color: '#778da9', marginBottom: '0.25rem' }}>Status</div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <div style={{
                                width: '8px',
                                height: '8px',
                                borderRadius: '50%',
                                background: streamError ? '#ef4444' : isLoading ? '#fbbf24' : '#4ade80',
                            }} />
                            <span style={{
                                color: streamError ? '#ef4444' : isLoading ? '#fbbf24' : '#4ade80',
                                fontSize: '0.85rem',
                                fontWeight: 600,
                            }}>
                                {streamError ? 'Error' : isLoading ? 'Connecting' : 'Live'}
                            </span>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
