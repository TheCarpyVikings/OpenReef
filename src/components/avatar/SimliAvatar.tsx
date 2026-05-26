'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { generateIceServers, generateSimliSessionToken, LogLevel, SimliClient } from 'simli-client';
import styles from './SimliAvatar.module.css';

interface SimliAvatarProps {
    apiKey: string;
    faceId: string;
    isTalking?: boolean;
    audioStream?: MediaStream;
    onConnected?: () => void;
    onDisconnected?: () => void;
}

const SimliAvatar: React.FC<SimliAvatarProps> = ({ apiKey, faceId, isTalking, audioStream, onConnected, onDisconnected }) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const audioRef = useRef<HTMLAudioElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const simliClientRef = useRef<SimliClient | null>(null);
    const audioStreamRef = useRef<MediaStream | undefined>(audioStream);
    const [isConnected, setIsConnected] = useState(false);
    const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

    // Handle mouse movement for "eyes following"
    const handleMouseMove = useCallback((e: MouseEvent) => {
        if (!containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;

        // Calculate normalized offset (-1 to 1)
        const dx = (e.clientX - centerX) / (rect.width / 2);
        const dy = (e.clientY - centerY) / (rect.height / 2);

        // Limit the range
        setMousePos({
            x: Math.max(-1, Math.min(1, dx)),
            y: Math.max(-1, Math.min(1, dy))
        });
    }, []);

    useEffect(() => {
        window.addEventListener('mousemove', handleMouseMove);
        return () => window.removeEventListener('mousemove', handleMouseMove);
    }, [handleMouseMove]);

    useEffect(() => {
        audioStreamRef.current = audioStream;
    }, [audioStream]);

    // Initialize Simli Client
    useEffect(() => {
        if (!apiKey || !faceId) return;

        const videoElement = videoRef.current;
        const audioElement = audioRef.current;
        if (!videoElement || !audioElement) {
            console.error('Simli: media elements not found');
            return;
        }

        let cancelled = false;

        const connect = async () => {
            try {
                const [{ session_token: sessionToken }, iceServers] = await Promise.all([
                    generateSimliSessionToken({
                        apiKey,
                        config: {
                            faceId,
                            handleSilence: false,
                            maxSessionLength: 3600,
                            maxIdleTime: 600,
                            model: 'fasttalk',
                        },
                    }),
                    generateIceServers(apiKey),
                ]);

                if (cancelled) return;

                const simliClient = new SimliClient(
                    sessionToken,
                    videoElement,
                    audioElement,
                    iceServers,
                    LogLevel.INFO,
                    'p2p',
                );
                simliClientRef.current = simliClient;

                simliClient.on('start', () => {
                    if (cancelled) return;
                    console.log('SIMLI: Connected to stream');
                    setIsConnected(true);
                    onConnected?.();
                });

                simliClient.on('stop', () => {
                    if (cancelled) return;
                    console.warn('SIMLI: Disconnected from stream');
                    setIsConnected(false);
                    onDisconnected?.();
                });

                simliClient.on('error', (message) => {
                    console.error('SIMLI: Connection error:', message);
                    setIsConnected(false);
                    onDisconnected?.();
                });

                simliClient.on('startup_error', (message) => {
                    console.error('SIMLI: Startup error:', message);
                    setIsConnected(false);
                    onDisconnected?.();
                });

                const audioTrack = audioStreamRef.current?.getAudioTracks()[0];
                if (audioTrack) {
                    console.log('SIMLI: Connecting initial audio track');
                    simliClient.listenToMediastreamTrack(audioTrack);
                }

                await simliClient.start();
            } catch (err) {
                if (!cancelled) {
                    console.error('SIMLI: Start error:', err);
                    setIsConnected(false);
                    onDisconnected?.();
                }
            }
        };

        void connect();

        return () => {
            cancelled = true;
            console.log('SIMLI: Closing client');
            simliClientRef.current?.stop().catch((err) => {
                console.warn('SIMLI: Stop error:', err);
            });
            simliClientRef.current = null;
        };
    }, [apiKey, faceId, onConnected, onDisconnected]);

    // Send audio to Simli when stream changes
    useEffect(() => {
        if (audioStream && simliClientRef.current) {
            const audioTrack = audioStream.getAudioTracks()[0];
            if (audioTrack) {
                console.log('SIMLI: Connecting updated audio track');
                simliClientRef.current.listenToMediastreamTrack(audioTrack);
            }
        }
    }, [audioStream]);

    // Apply the "eye following" effect - now more subtle head movement
    const eyeEffectStyle = {
        transform: `perspective(1000px) rotateY(${mousePos.x * 5}deg) rotateX(${-mousePos.y * 5}deg) scale(2.0)`,
        transition: 'transform 0.1s ease-out',
    };

    const glowStyle = {
        transform: `translate(${mousePos.x * 40}px, ${mousePos.y * 40}px)`,
        transition: 'transform 0.1s ease-out',
    };

    return (
        <div
            ref={containerRef}
            className={`${styles.coreContainer} ${isTalking ? styles.isTalking : ''}`}
        >
            {/* Rotating Outer Rings */}
            <div className={styles.outerRing} />
            <div className={styles.innerRing} />

            {/* Interactive Core Glow */}
            <div className={styles.coreGlow} style={glowStyle}>
                <div className={styles.glowDot} />
            </div>

            {/* Hologram Overlay & Masks */}
            <div className={styles.hologramOverlay} />
            <div className={styles.radialMask} />
            <div className={styles.breathingPulse} />
            <div className={styles.scanLines} />
            <div className={styles.bottomGlow} />

            <div className={styles.videoWrapper}>
                <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    style={eyeEffectStyle}
                    className={styles.avatarVideo}
                />
            </div>

            {/* Redundant audio element kept in DOM but not used by Simli config to avoid echo */}
            <audio ref={audioRef} autoPlay muted style={{ display: 'none' }} />

            {!isConnected && (
                <div className={styles.loadingOverlay}>
                    <div style={{ textAlign: 'center' }}>
                        <div className={styles.spinner} />
                        <p className={styles.loadingText}>Girding for Battle...</p>
                    </div>
                </div>
            )}
        </div>
    );
};

export default SimliAvatar;
