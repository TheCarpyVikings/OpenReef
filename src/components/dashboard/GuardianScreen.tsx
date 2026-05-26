'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import SimliAvatar from '@/components/avatar/SimliAvatar';
import { AIService, SystemStatus } from '@/lib/ai-service';
import { apiFetch } from '@/lib/api-fetch';
import { Send, Shield, Zap, RefreshCw, MessageSquare } from 'lucide-react';

export const GuardianScreen: React.FC = () => {
    const { settings, getLabel, getEquipmentName } = useSettings();
    const { entities } = useHomeAssistant();
    const [messages, setMessages] = useState<{ role: 'user' | 'ai'; text: string }[]>([]);
    const [input, setInput] = useState('');
    const [isTalking, setIsTalking] = useState(false);
    const [aiService, setAiService] = useState<AIService | null>(null);
    const [isThinking, setIsThinking] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);

    // Initialize AI Service
    useEffect(() => {
        if (settings.ai.geminiApiKey) {
            setAiService(new AIService(settings.ai.geminiApiKey));
        }

        // Pre-load voices for reliability
        if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
            window.speechSynthesis.getVoices();
            const handleVoicesChanged = () => {
                window.speechSynthesis.getVoices();
            };
            window.speechSynthesis.addEventListener('voiceschanged', handleVoicesChanged);
            return () => window.speechSynthesis.removeEventListener('voiceschanged', handleVoicesChanged);
        }
    }, [settings.ai.geminiApiKey]);

    // Scroll to bottom of chat
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages]);

    // Gather System Status for AI
    const getSystemStatus = useCallback((): SystemStatus => {
        const status: SystemStatus = {
            alerts: [],
            warnings: [],
            overdueTasks: [],
            sensorReadings: {}
        };

        // 1. Gather Sensor Readings & Alerts from Levels
        const sensorIds = ['temp', 'ph', 'salinity', 'orp', 'do', 'room_temp', 'co2', 'humidity'];
        sensorIds.forEach(id => {
            const tankKey = id as keyof typeof settings.entities.tank;
            const roomKey = id === 'room_temp' ? 'temp' : id;
            const entityId = settings.entities.tank[tankKey]
                || settings.entities.room?.[roomKey as keyof typeof settings.entities.room];
            if (entityId) {
                const state = entities?.[entityId]?.state;
                const threshold = settings.thresholds[id];
                const val = parseFloat(state || '');
                const isIssue = threshold && !isNaN(val) && (val < threshold.min || val > threshold.max);

                status.sensorReadings[getLabel(id)] = {
                    value: state || 'unknown',
                    unit: id === 'temp' || id === 'room_temp' ? '°C' : id === 'ph' ? '' : id === 'salinity' ? 'ppt' : id === 'co2' ? 'ppm' : id === 'humidity' ? '%' : '',
                    range: threshold ? `${threshold.min}-${threshold.max}` : undefined,
                    isIssue: isIssue
                };

                if (isIssue) {
                    status.alerts.push(`${getLabel(id)} is outside safe range! (${state})`);
                }
            }
        });

        // 2. Custom Alarms
        Object.values(settings.alarms || {}).forEach(alarm => {
            const state = entities?.[alarm.entityId]?.state;
            const isOk = state === alarm.okValue || (alarm.okValue.toLowerCase() === 'off' && state === 'off') || (alarm.okValue.toLowerCase() === 'on' && state === 'on');
            if (!isOk) {
                const list = alarm.severity === 'critical' ? status.alerts : status.warnings;
                list.push(`${alarm.label}: ${alarm.description || state}`);
            }
        });

        // 3. Equipment Status
        settings.missionControl.criticalEquipment.forEach(key => {
            const equip = settings.entities.equipment[key];
            const state = entities?.[equip?.switch]?.state;
            if (state === 'off') {
                status.warnings.push(`${getEquipmentName(key, key)} is Currently Powered Down!`);
            }
        });

        return status;
    }, [settings, entities, getLabel, getEquipmentName]);

    const [audioStream, setAudioStream] = useState<MediaStream | undefined>(undefined);
    const audioContextRef = useRef<AudioContext | null>(null);

    // Initializing AudioContext on first user interaction if needed
    const getAudioContext = () => {
        if (!audioContextRef.current) {
            const audioWindow = window as Window & typeof globalThis & {
                webkitAudioContext?: typeof AudioContext;
            };
            const AudioContextConstructor = window.AudioContext || audioWindow.webkitAudioContext;
            if (!AudioContextConstructor) {
                throw new Error('AudioContext is not available in this browser');
            }
            audioContextRef.current = new AudioContextConstructor();
        }
        return audioContextRef.current;
    };

    // Diagnostic Beep
    const playTestTone = () => {
        try {
            const context = getAudioContext();
            const oscillator = context.createOscillator();
            const gain = context.createGain();

            oscillator.type = 'sine';
            oscillator.frequency.setValueAtTime(440, context.currentTime);
            gain.gain.setValueAtTime(0.1, context.currentTime);

            oscillator.connect(gain);
            gain.connect(context.destination);

            oscillator.start();
            oscillator.stop(context.currentTime + 0.1);
            console.log('Diagnostic tone played');
        } catch (e) {
            console.error('AudioContext error:', e);
        }
    };

    // Handle Speaking via OpenAI TTS for Lip-Sync
    const speak = async (text: string) => {
        console.log('LAGERTHA SPEAKING:', text.substring(0, 30) + '...');

        try {
            setIsTalking(true);

            const response = await apiFetch('/api/tts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text,
                    voice: 'shimmer' // Authority voice
                })
            });

            if (!response.ok) throw new Error('TTS Fetch failed');

            const audioDataArr = await response.arrayBuffer();
            const context = getAudioContext();
            const audioBuffer = await context.decodeAudioData(audioDataArr);

            const source = context.createBufferSource();
            const destination = context.createMediaStreamDestination();

            source.buffer = audioBuffer;

            // Connect to speakers AND to the MediaStream for Simli
            source.connect(context.destination);
            source.connect(destination);

            const track = destination.stream.getAudioTracks()[0];
            if (!track) throw new Error('No audio track found in destination');

            setAudioStream(destination.stream);

            source.onended = () => {
                setIsTalking(false);
                setAudioStream(undefined);
            };

            source.start(0);
            console.log('OpenAI TTS playing locally + streaming to Simli');

        } catch (error) {
            console.error('OpenAI TTS Error:', error);
            setIsTalking(false);
            speakFallback(text);
        }
    };

    // Fallback if OpenAI key is missing
    const speakFallback = (text: string) => {
        if (!('speechSynthesis' in window)) return;
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        const voices = window.speechSynthesis.getVoices();
        const preferredVoices = ['Samantha', 'Karen', 'Victoria', 'Moira', 'Fiona'];
        let vikingVoice = null;

        for (const name of preferredVoices) {
            vikingVoice = voices.find(v => v.name.includes(name));
            if (vikingVoice) break;
        }

        if (!vikingVoice) {
            vikingVoice = voices.find(v => v.name.toLowerCase().includes('female')) || voices[0];
        }

        utterance.voice = vikingVoice;
        utterance.onstart = () => setIsTalking(true);
        utterance.onend = () => setIsTalking(false);
        utterance.onerror = () => setIsTalking(false);
        window.speechSynthesis.speak(utterance);
    };

    const handleSendMessage = async (textOverride?: string) => {
        const messageText = textOverride || input;
        if (!messageText.trim() || !aiService || isThinking) return;

        const newUserMessage = { role: 'user' as const, text: messageText };
        setMessages(prev => [...prev, newUserMessage]);
        setInput('');
        setIsThinking(true);

        const status = getSystemStatus();
        const response = await aiService.getResponse(messageText, status);

        setMessages(prev => [...prev, { role: 'ai' as const, text: response }]);
        setIsThinking(false);

        // Speak the response
        speak(response);
    };

    return (
        <div className={styles.missionControl} style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 180px)', gap: '1.5rem' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2rem', height: '100%', minHeight: 0 }}>

                {/* Left Side: Avatar & Controls */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', justifyContent: 'center', alignItems: 'center' }}>
                    <SimliAvatar
                        apiKey={settings.ai.simliApiKey}
                        faceId={settings.ai.faceId}
                        isTalking={isTalking}
                        audioStream={audioStream}
                    />

                    <div style={{ textAlign: 'center' }}>
                        <h2 style={{ fontSize: '2rem', color: 'var(--primary-color)', marginBottom: '0.5rem', letterSpacing: '0.1em' }}>LAGERTHA</h2>
                        <p style={{ color: '#778da9', fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '0.2em' }}>Guardian of the Realm</p>
                    </div>

                    <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                        <button
                            className={styles.tabItem}
                            onClick={() => handleSendMessage("Hey Lagertha, can I have a reef status please?")}
                            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(0, 180, 216, 0.1)', borderColor: 'rgba(0, 180, 216, 0.3)' }}
                        >
                            <Shield size={16} /> Request Reef Status
                        </button>
                        <button
                            className={styles.tabItem}
                            onClick={() => handleSendMessage("Is there any danger approaching my subjects today?")}
                            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(239, 68, 68, 0.1)', borderColor: 'rgba(239, 68, 68, 0.3)' }}
                        >
                            <Zap size={16} /> Check for Dangers
                        </button>
                        <button
                            className={styles.tabItem}
                            onClick={() => {
                                playTestTone();
                                speak("Voice systems check: The realm is secure, Shieldbrother. Can you hear my words?");
                            }}
                            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(255, 255, 255, 0.05)', borderColor: 'rgba(255, 255, 255, 0.1)' }}
                        >
                            <RefreshCw size={16} /> Test Comms & Beep
                        </button>
                        <button
                            className={styles.tabItem}
                            onClick={() => window.speechSynthesis.cancel()}
                            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(255, 255, 255, 0.05)', borderColor: 'rgba(255, 255, 255, 0.1)' }}
                        >
                            Stop Speech
                        </button>
                    </div>
                </div>

                {/* Right Side: Chat Interface */}
                <div className={styles.card} style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', padding: 0, border: '1px solid rgba(255,255,255,0.05)' }}>
                    <div style={{ padding: '1rem', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', gap: '0.75rem', background: 'rgba(255,255,255,0.02)' }}>
                        <MessageSquare size={18} color="var(--primary-color)" />
                        <span style={{ fontSize: '0.9rem', fontWeight: 600, letterSpacing: '0.05em' }}>GUARDIAN LOG</span>
                    </div>

                    <div
                        ref={scrollRef}
                        style={{ flex: 1, overflowY: 'auto', padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}
                    >
                        {messages.length === 0 && (
                            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#778da9', fontSize: '0.9rem', fontStyle: 'italic', textAlign: 'center', padding: '2rem' }}>
                                &quot;I wait for your command, Shieldbrother. The realm is quiet for now.&quot;
                            </div>
                        )}
                        {messages.map((m, i) => (
                            <div key={i} style={{
                                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                                maxWidth: '85%',
                                padding: '1rem 1.25rem',
                                borderRadius: m.role === 'user' ? '18px 18px 4px 18px' : '18px 18px 18px 4px',
                                background: m.role === 'user' ? 'var(--primary-color)' : 'rgba(255,255,255,0.05)',
                                color: m.role === 'user' ? '#fff' : '#e0e1dd',
                                fontSize: '0.95rem',
                                lineHeight: '1.5',
                                boxShadow: m.role === 'user' ? '0 4px 15px rgba(var(--primary-rgb), 0.2)' : 'none'
                            }}>
                                {m.text}
                            </div>
                        ))}
                        {isThinking && (
                            <div style={{ alignSelf: 'flex-start', padding: '1rem', borderRadius: '18px', background: 'rgba(255,255,255,0.02)', display: 'flex', gap: '0.5rem' }}>
                                <div className={styles.spin}><RefreshCw size={16} color="var(--primary-color)" /></div>
                                <span style={{ fontSize: '0.85rem', color: '#778da9' }}>Lagertha is consulting the runes...</span>
                            </div>
                        )}
                    </div>

                    <div style={{ padding: '1.5rem', background: 'rgba(255,255,255,0.02)', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                        <div style={{ display: 'flex', gap: '1rem' }}>
                            <input
                                type="text"
                                className={styles.input}
                                placeholder="Speak to the Guardian..."
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                                style={{ flex: 1, background: 'rgba(0,0,0,0.2)' }}
                            />
                            <button
                                onClick={() => handleSendMessage()}
                                className={styles.addButton}
                                disabled={!input.trim() || isThinking}
                                style={{ width: '48px', minWidth: '48px', height: '48px', padding: 0 }}
                            >
                                <Send size={20} />
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
