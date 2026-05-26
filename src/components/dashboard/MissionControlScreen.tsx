'use client';

import React, { useState } from 'react';
import styles from '@/app/dashboard.module.css';
import { useSettings } from '@/context/SettingsContext';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { Power, Clock } from 'lucide-react';
import { apiFetch } from '@/lib/api-fetch';
import { ReefHealthScore } from './ReefHealthScore';
import { AIChemistryAdvisor } from './AIChemistryAdvisor';
import type { HealthScoreInput } from './ReefHealthScore';
import { useNow } from '@/hooks/use-now';
import type { ReefTask } from '@/types/reef';

interface MissionControlScreenProps {
    tasks: ReefTask[];
    setTasks: React.Dispatch<React.SetStateAction<ReefTask[]>>;
    setActiveTab: (tab: string) => void;
    setSettingsDeepLink: (link: { section?: string; alarmId?: string } | null) => void;
}

export const MissionControlScreen: React.FC<MissionControlScreenProps> = ({
    tasks,
    setTasks,
    setActiveTab,
    setSettingsDeepLink,
}) => {
    const { settings, getEquipmentName, getLabel, manualReadings, updateNestedSetting } = useSettings();
    const { entities, toggleSwitch, turnOnSwitch, turnOffSwitch } = useHomeAssistant();
    const now = useNow(60 * 60 * 1000);

    const getEntityState = (entityId: string | undefined) => entityId ? entities?.[entityId]?.state : undefined;

    const getLatestManualValue = (id: string) => {
        const readings = manualReadings[id];
        if (!readings || readings.length === 0) return '--';
        return readings[readings.length - 1].value.toString();
    };

    // --- Health calculations ---
    const customAlarms = Object.entries(settings.alarms || {}).map(([id, alarm]) => {
        const state = getEntityState(alarm.entityId);
        const isOk = state === alarm.okValue || (alarm.okValue.toLowerCase() === 'off' && state === 'off') || (alarm.okValue.toLowerCase() === 'on' && state === 'on');
        return { ...alarm, id, isOk, currentState: state || 'unknown' };
    });

    const sensorIssues = settings.missionControl.environmentalStats.map(id => {
        let entityId = '';
        if (settings.entities.tank[id as keyof typeof settings.entities.tank]) {
            entityId = settings.entities.tank[id as keyof typeof settings.entities.tank];
        } else if (settings.entities.room[id as keyof typeof settings.entities.room]) {
            entityId = settings.entities.room[id as keyof typeof settings.entities.room];
        } else {
            const latestManual = getLatestManualValue(id);
            return { id, label: getLabel(id), value: latestManual === '--' ? NaN : parseFloat(latestManual) };
        }
        const state = getEntityState(entityId);
        return { id, label: getLabel(id), value: state ? parseFloat(state) : NaN };
    }).filter(s => {
        const range = settings.thresholds[s.id];
        return range && !isNaN(s.value) && (s.value < range.min || s.value > range.max);
    });

    const criticalEquip = settings.missionControl.criticalEquipment.map(key => ({
        key,
        label: getEquipmentName(key, key),
        state: getEntityState(settings.entities.equipment[key]?.switch),
        power: parseFloat(getEntityState(settings.entities.equipment[key]?.power) || '0'),
        switchEntity: settings.entities.equipment[key]?.switch
    }));

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const todayStr = today.toISOString().split('T')[0];

    const activeTasks = tasks.filter(t => !t.completed && t.due);
    const taskIssues = activeTasks.map(t => {
        const dueDate = new Date(t.due!);
        dueDate.setHours(0, 0, 0, 0);
        const isOverdue = dueDate < today;
        const isDueToday = t.due === todayStr;
        return { ...t, isOverdue, isDueToday };
    }).filter(t => t.isOverdue || t.isDueToday)
        .sort((a, b) => new Date(a.due!).getTime() - new Date(b.due!).getTime());

    const hasCritical = customAlarms.some(a => !a.isOk && a.severity === 'critical') || sensorIssues.length > 0 || taskIssues.some(t => t.isOverdue);
    const hasWarning = customAlarms.some(a => !a.isOk && a.severity === 'warning') || criticalEquip.some(e => e.state === 'off') || taskIssues.some(t => t.isDueToday);

    const statusColor = hasCritical ? '#ef4444' : hasWarning ? '#fbbf24' : '#4ade80';
    const statusText = hasCritical ? 'CRITICAL SYSTEM ALERT' : hasWarning ? 'SYSTEM WARNING' : 'ALL SYSTEMS NOMINAL';

    // --- AI Advisor state ---
    const [advisorExpanded, setAdvisorExpanded] = useState(false);

    // --- Build HealthScoreInput ---
    const healthInput: HealthScoreInput = (() => {
        const sensorData = settings.missionControl.environmentalStats.map(id => {
            let entityId = '';
            if (settings.entities.tank[id as keyof typeof settings.entities.tank]) {
                entityId = settings.entities.tank[id as keyof typeof settings.entities.tank];
            } else if (settings.entities.room[id as keyof typeof settings.entities.room]) {
                entityId = settings.entities.room[id as keyof typeof settings.entities.room];
            }
            const state = entityId ? getEntityState(entityId) : undefined;
            const threshold = settings.thresholds[id];
            return {
                id,
                value: state ? parseFloat(state) : NaN,
                min: threshold?.min ?? 0,
                max: threshold?.max ?? 100,
            };
        }).filter(s => !isNaN(s.value));

        const manualParams = ['alk', 'calc', 'mag', 'salinity', 'nitrate', 'phosphate'];
        const manualData = manualParams.map(id => {
            const readings = manualReadings[id];
            if (!readings || readings.length === 0) return null;
            const latest = readings[readings.length - 1];
            const ageHours = now === 0 ? 0 : (now - new Date(latest.date).getTime()) / (1000 * 60 * 60);
            const threshold = settings.thresholds[id];
            return {
                id,
                value: parseFloat(latest.value.toString()),
                min: threshold?.min ?? 0,
                max: threshold?.max ?? 100,
                ageHours,
            };
        }).filter(Boolean) as { id: string; value: number; min: number; max: number; ageHours: number }[];

        const alarmData = customAlarms.map(a => ({
            severity: a.severity as 'critical' | 'warning',
            isOk: a.isOk,
        }));

        const equipData = settings.missionControl.criticalEquipment.map(key => ({
            key,
            isOn: getEntityState(settings.entities.equipment[key]?.switch) === 'on',
            isCritical: true,
        }));

        const overdueCount = taskIssues.filter(t => t.isOverdue).length;
        const dueTodayCount = taskIssues.filter(t => t.isDueToday).length;

        return {
            sensorReadings: sensorData,
            manualReadings: manualData,
            alarms: alarmData,
            equipment: equipData,
            tasks: { overdue: overdueCount, dueToday: dueTodayCount, totalActive: activeTasks.length },
        };
    })();

    // --- Build AI Advisor props ---
    const advisorSensorReadings = (() => {
        return settings.missionControl.environmentalStats.map(id => {
            let entityId = '';
            if (settings.entities.tank[id as keyof typeof settings.entities.tank]) {
                entityId = settings.entities.tank[id as keyof typeof settings.entities.tank];
            } else if (settings.entities.room[id as keyof typeof settings.entities.room]) {
                entityId = settings.entities.room[id as keyof typeof settings.entities.room];
            }
            const state = entityId ? getEntityState(entityId) : undefined;
            const threshold = settings.thresholds[id];
            return {
                id,
                label: getLabel(id),
                value: state ? parseFloat(state) : NaN,
                min: threshold?.min ?? 0,
                max: threshold?.max ?? 100,
            };
        }).filter(s => !isNaN(s.value));
    })();

    const advisorManualReadings = (() => {
        const manualParams = ['alk', 'calc', 'mag', 'salinity', 'nitrate', 'phosphate'];
        return manualParams.map(id => {
            const readings = manualReadings[id];
            const threshold = settings.thresholds[id];
            return {
                id,
                label: getLabel(id),
                values: (readings || []).map((reading) => ({ value: reading.value, date: reading.date })),
                min: threshold?.min ?? 0,
                max: threshold?.max ?? 100,
            };
        }).filter(m => m.values.length > 0);
    })();

    const defaultSections = ['health_score', 'ai_advisor', 'alarms', 'chemistry', 'equipment', 'tasks'];
    let sectionOrder = settings.missionControl.sectionOrder || defaultSections;

    // Ensure new mandatory sections are included even if user has a custom order saved
    const mandatory = ['health_score', 'ai_advisor'];
    const missing = mandatory.filter(id => !sectionOrder.includes(id));
    if (missing.length > 0) {
        sectionOrder = [...missing, ...sectionOrder];
    }

    // --- Quick action: mark task done ---
    const handleQuickComplete = async (taskId: string) => {
        try {
            const task = tasks.find(t => t.id === taskId);

            await apiFetch(`/api/tasks`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'update', taskId: taskId, listId: task?.listId, completed: true })
            });
            setTasks(prev => prev.map(t => t.id === taskId ? { ...t, completed: true } : t));
        } catch (err) {
            console.error('Failed to complete task:', err);
        }
    };

    // --- Drag and drop handlers ---
    const handleDragStart = (e: React.DragEvent, sectionId: string) => {
        e.dataTransfer.setData('text/plain', sectionId);
        e.dataTransfer.effectAllowed = 'move';
        (e.currentTarget as HTMLElement).style.opacity = '0.5';
    };

    const handleDragEnd = (e: React.DragEvent) => {
        (e.currentTarget as HTMLElement).style.opacity = '1';
    };

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        (e.currentTarget as HTMLElement).style.borderTop = '2px solid var(--primary-color, #00b4d8)';
    };

    const handleDragLeave = (e: React.DragEvent) => {
        (e.currentTarget as HTMLElement).style.borderTop = 'none';
    };

    const handleDrop = (e: React.DragEvent, targetId: string) => {
        e.preventDefault();
        (e.currentTarget as HTMLElement).style.borderTop = 'none';
        const draggedId = e.dataTransfer.getData('text/plain');
        if (draggedId === targetId) return;

        const currentOrder = [...sectionOrder];
        const fromIdx = currentOrder.indexOf(draggedId);
        const toIdx = currentOrder.indexOf(targetId);
        if (fromIdx === -1 || toIdx === -1) return;

        currentOrder.splice(fromIdx, 1);
        currentOrder.splice(toIdx, 0, draggedId);
        updateNestedSetting('missionControl', { sectionOrder: currentOrder });
    };

    // --- Styles ---
    const quickActionStyle: React.CSSProperties = {
        padding: '0.3rem 0.7rem',
        borderRadius: '6px',
        border: '1px solid rgba(255,255,255,0.15)',
        background: 'rgba(255,255,255,0.05)',
        color: '#e0e1dd',
        fontSize: '0.7rem',
        fontWeight: 600,
        cursor: 'pointer',
        transition: 'all 0.2s',
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.3rem',
        marginTop: '0.5rem',
    };

    const dragHandleStyle: React.CSSProperties = {
        cursor: 'grab',
        opacity: 0.4,
        fontSize: '1rem',
        userSelect: 'none',
        marginRight: '0.5rem',
    };

    // --- Section renderers ---
    const sections: Record<string, { title: string; render: () => React.ReactNode }> = {
        health_score: {
            title: 'Reef Health Score',
            render: () => (
                <ReefHealthScore input={healthInput} />
            )
        },
        ai_advisor: {
            title: 'AI Chemistry Advisor',
            render: () => (
                <AIChemistryAdvisor
                    sensorReadings={advisorSensorReadings}
                    manualReadings={advisorManualReadings}
                    expanded={advisorExpanded}
                    onToggleExpanded={() => setAdvisorExpanded(!advisorExpanded)}
                />
            )
        },
        alarms: {
            title: 'Health Monitors',
            render: () => (
                <div style={{ display: 'grid', gap: '1rem' }}>
                    {customAlarms.length === 0 ? (
                        <div className={styles.card} style={{ backgroundColor: 'transparent', border: '1px dashed #27272a', textAlign: 'center', padding: '2rem' }}>
                            <p style={{ color: '#778da9', margin: 0 }}>No custom monitors configured.</p>
                            <button onClick={() => { setSettingsDeepLink({ section: 'mission' }); setActiveTab('settings'); }} style={{ color: '#00b4d8', background: 'none', border: 'none', padding: 0, marginTop: '0.5rem', cursor: 'pointer' }}>Add Alerts</button>
                        </div>
                    ) : (
                        customAlarms.map((alarm, idx) => (
                            <div key={idx} className={styles.card} style={{ borderLeft: `4px solid ${alarm.isOk ? '#4ade80' : alarm.severity === 'critical' ? '#ef4444' : '#fbbf24'}` }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: '0.9rem', color: '#e0e1dd', fontWeight: 600 }}>{alarm.label}</div>
                                        {!alarm.isOk && alarm.description && (
                                            <div style={{
                                                fontSize: '0.85rem',
                                                color: alarm.severity === 'critical' ? '#fca5a5' : '#fde68a',
                                                fontStyle: 'italic',
                                                marginTop: '0.5rem',
                                                lineHeight: '1.4'
                                            }}>
                                                {alarm.description}
                                            </div>
                                        )}
                                        {!alarm.isOk && (
                                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                                <button
                                                    style={quickActionStyle}
                                                    onClick={(e) => { e.stopPropagation(); setSettingsDeepLink({ section: 'mission', alarmId: alarm.id }); setActiveTab('settings'); }}
                                                >
                                                    ⚙️ Settings
                                                </button>
                                                {alarm.entityId.startsWith('switch.') && (
                                                    <button
                                                        style={{ ...quickActionStyle, borderColor: 'rgba(74, 222, 128, 0.3)', color: '#4ade80' }}
                                                        onClick={(e) => { e.stopPropagation(); toggleSwitch(alarm.entityId); }}
                                                    >
                                                        ⚡ Toggle
                                                    </button>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                    <div style={{ textAlign: 'right' }}>
                                        <div style={{ color: alarm.isOk ? '#4ade80' : alarm.severity === 'critical' ? '#ef4444' : '#fbbf24', fontWeight: 700 }}>
                                            {(() => {
                                                const val = parseFloat(alarm.currentState);
                                                return !isNaN(val) ? val.toFixed(2) : alarm.currentState.toUpperCase();
                                            })()}
                                        </div>
                                        {!alarm.isOk && <div style={{ fontSize: '0.65rem', color: '#778da9' }}>EXPECTED: {alarm.okValue}</div>}
                                    </div>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            )
        },
        chemistry: {
            title: 'Chemistry',
            render: () => (
                <div style={{ display: 'grid', gap: '1rem' }}>
                    {settings.missionControl.environmentalStats.map(id => {
                        const threshold = settings.thresholds[id];
                        let valStr = '--';
                        let entityId = '';

                        if (settings.entities.tank[id as keyof typeof settings.entities.tank]) {
                            entityId = settings.entities.tank[id as keyof typeof settings.entities.tank];
                        } else if (settings.entities.room?.[id as keyof typeof settings.entities.room]) {
                            entityId = settings.entities.room[id as keyof typeof settings.entities.room];
                        } else if (id === 'room_temp') {
                            entityId = settings.entities.room?.temp;
                        }

                        if (entityId) {
                            valStr = getEntityState(entityId) || '--';
                        } else {
                            valStr = getLatestManualValue(id);
                        }

                        const val = parseFloat(valStr);
                        const isIssue = threshold && !isNaN(val) && (val < threshold.min || val > threshold.max);

                        let lastTestedStr: string | undefined = undefined;
                        let isStale = false;
                        if (!entityId && manualReadings[id] && manualReadings[id].length > 0) {
                            const latest = manualReadings[id][manualReadings[id].length - 1];
                            const dObj = new Date(latest.date);
                            try {
                                lastTestedStr = dObj.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
                            } catch {
                                lastTestedStr = latest.date;
                            }
                            const daysSince = (Date.now() - dObj.getTime()) / (1000 * 60 * 60 * 24);
                            if (id === 'alk') isStale = daysSince > 7;
                            else if (id === 'calc' || id === 'mag' || id === 'salinity') isStale = daysSince > 14;
                            else isStale = daysSince > 14;
                        }

                        return (
                            <div key={id} className={styles.card} style={{ borderLeft: `4px solid ${isIssue ? '#ef4444' : '#4ade80'}` }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span>{getLabel(id)}</span>
                                    <div style={{ textAlign: 'right' }}>
                                        <div style={{ color: isIssue ? '#ef4444' : '#4ade80', fontWeight: 700 }}>
                                            {!isNaN(val) ? val.toFixed(2) : valStr}
                                        </div>
                                        <div style={{ fontSize: '0.65rem', color: '#778da9' }}>
                                            {lastTestedStr && (
                                                <span style={{ color: isStale ? '#ef4444' : 'inherit', fontWeight: isStale ? 600 : 'inherit', marginRight: '4px' }}>
                                                    {lastTestedStr} •
                                                </span>
                                            )}
                                            RANGE: {threshold?.min}-{threshold?.max}
                                        </div>
                                    </div>
                                </div>
                                {isIssue && (
                                    <button
                                        style={{ ...quickActionStyle, borderColor: 'rgba(0, 180, 216, 0.3)', color: '#00b4d8' }}
                                        onClick={(e) => { e.stopPropagation(); setActiveTab('live'); }}
                                    >
                                        📊 View History →
                                    </button>
                                )}
                            </div>
                        );
                    })}
                </div>
            )
        },
        equipment: {
            title: 'Critical Equipment',
            render: () => (
                <div style={{ display: 'grid', gap: '1rem' }}>
                    {criticalEquip.map(equip => {
                        const isOk = equip.state === 'on';
                        return (
                            <div key={equip.key} className={styles.card} style={{ borderLeft: `4px solid ${isOk ? '#4ade80' : '#fbbf24'}` }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span>{equip.label}</span>
                                    <div style={{ textAlign: 'right' }}>
                                        <div style={{ color: isOk ? '#4ade80' : '#fbbf24', fontWeight: 700 }}>{equip.state?.toUpperCase() || 'OFF'}</div>
                                        <div style={{ fontSize: '0.65rem', color: '#778da9' }}>{equip.power.toFixed(2)} W</div>
                                    </div>
                                </div>
                                {equip.switchEntity && (
                                    <button
                                        style={{
                                            ...quickActionStyle,
                                            borderColor: isOk ? 'rgba(251, 191, 36, 0.3)' : 'rgba(74, 222, 128, 0.3)',
                                            color: isOk ? '#fbbf24' : '#4ade80'
                                        }}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            if (isOk) {
                                                turnOffSwitch(equip.switchEntity);
                                            } else {
                                                turnOnSwitch(equip.switchEntity);
                                            }
                                        }}
                                    >
                                        <Power size={12} /> {isOk ? 'Turn OFF' : 'Turn ON'}
                                    </button>
                                )}
                            </div>
                        );
                    })}
                </div>
            )
        },
        tasks: {
            title: 'Task Monitoring',
            render: () => (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem' }}>
                    {taskIssues.length === 0 ? (
                        <div className={styles.card} style={{ gridColumn: '1 / -1', backgroundColor: 'transparent', border: '1px dashed #27272a', textAlign: 'center', padding: '2rem' }}>
                            <p style={{ color: '#778da9', margin: 0 }}>No urgent tasks. Your schedule is clear!</p>
                            <button onClick={() => setActiveTab('tasks')} style={{ color: '#00b4d8', background: 'none', border: 'none', padding: 0, marginTop: '0.5rem', cursor: 'pointer' }}>View All Tasks</button>
                        </div>
                    ) : (
                        taskIssues.map(task => (
                            <div key={task.id} className={styles.card} style={{ borderLeft: `4px solid ${task.isOverdue ? '#ef4444' : '#fbbf24'}` }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: '0.9rem', color: '#e0e1dd', fontWeight: 600 }}>{task.title}</div>
                                        <div style={{
                                            fontSize: '0.8rem',
                                            color: task.isOverdue ? '#fca5a5' : '#fde68a',
                                            fontWeight: 600,
                                            marginTop: '0.5rem',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.4rem'
                                        }}>
                                            <Clock size={14} />
                                            {task.isOverdue ? 'OVERDUE' : 'DUE TODAY'}
                                        </div>
                                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.25rem' }}>
                                            <button
                                                style={{ ...quickActionStyle, borderColor: 'rgba(74, 222, 128, 0.3)', color: '#4ade80' }}
                                                onClick={(e) => { e.stopPropagation(); handleQuickComplete(task.id); }}
                                            >
                                                ✓ Done
                                            </button>
                                            <button
                                                style={{ ...quickActionStyle, borderColor: 'rgba(0, 180, 216, 0.3)', color: '#00b4d8' }}
                                                onClick={(e) => { e.stopPropagation(); setActiveTab('tasks'); }}
                                            >
                                                View →
                                            </button>
                                        </div>
                                    </div>
                                    <div style={{ textAlign: 'right' }}>
                                        <div style={{ color: task.isOverdue ? '#ef4444' : '#fbbf24', fontWeight: 700, fontSize: '0.8rem' }}>
                                            {new Date(task.due!).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
                                        </div>
                                        <div style={{ fontSize: '0.65rem', color: '#778da9', marginTop: '4px' }}>{task.category}</div>
                                    </div>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            )
        }
    };



    return (
        <div className={styles.missionControl}>
            <div className={styles.statusBanner} style={{ backgroundColor: `${statusColor}20`, borderColor: statusColor }}>
                <div className={styles.statusDot} style={{ backgroundColor: statusColor, width: '12px', height: '12px', boxShadow: `0 0 10px ${statusColor}` }} />
                <h2 style={{ color: statusColor, margin: 0, fontSize: '1.5rem', letterSpacing: '0.05em' }}>{statusText}</h2>
            </div>

            <div style={{ fontSize: '0.7rem', color: '#778da9', textAlign: 'center', marginTop: '0.75rem', opacity: 0.6 }}>
                ⠿ Drag sections to reorder
            </div>

            {sectionOrder.map(sectionId => {
                const section = sections[sectionId];
                if (!section) return null;

                return (
                    <section
                        key={sectionId}
                        className={styles.missionSection}
                        style={{ marginTop: '1.5rem' }}
                        draggable
                        onDragStart={(e) => handleDragStart(e, sectionId)}
                        onDragEnd={handleDragEnd}
                        onDragOver={handleDragOver}
                        onDragLeave={handleDragLeave}
                        onDrop={(e) => handleDrop(e, sectionId)}
                    >
                        <h3 className={styles.sectionSubtitle} style={{ cursor: 'grab', display: 'flex', alignItems: 'center' }}>
                            <span style={dragHandleStyle}>⠿</span>
                            {section.title}
                        </h3>
                        {section.render()}
                    </section>
                );
            })}
        </div>
    );
};
