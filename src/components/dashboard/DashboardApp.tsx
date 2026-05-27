'use client';

import React, { useState, useEffect, useCallback } from 'react';
import styles from '@/app/dashboard.module.css';
import { useHomeAssistant } from '@/hooks/use-home-assistant';
import { apiFetch, withIngressPath } from '@/lib/api-fetch';
import { EntitySwitch } from '@/components/dashboard/EntitySwitch';
import { Zap, Shield, Coffee, Activity, Waves, Lightbulb, Power, ClipboardList, Settings, Clock, Layout, Droplets, FileText, Video, TrendingUp } from 'lucide-react';
import { TasksScreen } from '@/components/dashboard/TasksScreen';
import { SettingsScreen } from '@/components/dashboard/SettingsScreen';
import { SpawningScreen } from '@/components/dashboard/SpawningScreen';
import { GuardianScreen } from '@/components/dashboard/GuardianScreen';
import { LightsScreen } from '@/components/dashboard/LightsScreen';
import { WaterChangeScreen } from '@/components/dashboard/WaterChangeScreen';
import { ReefDiagramScreen } from '@/components/dashboard/ReefDiagramScreen';
import { MissionControlScreen } from '@/components/dashboard/MissionControlScreen';
import { LiveStatsScreen } from '@/components/dashboard/LiveStatsScreen';
import { ManualStatsScreen } from '@/components/dashboard/ManualStatsScreen';
import { EnergyScreen } from '@/components/dashboard/EnergyScreen';
import { ReportsScreen } from '@/components/dashboard/ReportsScreen';
import { CameraScreen } from '@/components/dashboard/CameraScreen';
import { OceanSeaWavesScreen } from '@/components/dashboard/OceanSeaWavesScreen';
import { AnalyticsScreen } from '@/components/dashboard/AnalyticsScreen';
import { ParamHistoryModal } from '@/components/dashboard/ParamHistoryModal';
import { EquipmentDetailModal } from '@/components/dashboard/EquipmentDetailModal';
import { SettingsProvider, useSettings } from '@/context/SettingsContext';
import { findMidnightValue, historyResponseToPoints } from '@/lib/ha-history';
import type { DashboardTab, DataPoint, EquipmentModeState, ReefTask } from '@/types/reef';

function DashboardContent() {
  const { settings, getEquipmentName, updateNestedSetting, setActiveModeExpiry, activeModeExpiry } = useSettings();
  const { entities, isConnected, toggleSwitch, turnOffSwitch, turnOnSwitch, fetchHistory, error, reconnect } = useHomeAssistant();
  const [activeTab, setActiveTab] = useState<DashboardTab>('mission');
  const [selectedParam, setSelectedParam] = useState<{ id: string; label: string; color: string; isManual: boolean } | null>(null);
  const [selectedEquipment, setSelectedEquipment] = useState<{ label: string; entityId: string; icon: React.ReactNode } | null>(null);
  const [midnightEnergies, setMidnightEnergies] = useState<Record<string, number>>({});
  const [dashboardHistory, setDashboardHistory] = useState<Record<string, DataPoint[]>>({});
  const [tasks, setTasks] = useState<ReefTask[]>([]);
  const [settingsDeepLink, setSettingsDeepLink] = useState<{ section?: string; alarmId?: string } | null>(null);
  const logoSrc = withIngressPath('/openreef-logo.png');

  // Fetch midnight energies for delta calculation
  const fetchMidnightEnergies = useCallback(async () => {
    if (!isConnected) return;
    const equipmentEntities = Object.values(settings.entities.equipment);
    const energyEntityIds = equipmentEntities.map(e => e.energy).filter(Boolean);

    for (const entityId of energyEntityIds) {
      try {
        const data = await fetchHistory(entityId, 24);
        if (data) {
          const now = new Date();
          const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
          setMidnightEnergies(prev => ({ ...prev, [entityId]: findMidnightValue(data, entityId, midnight) }));
        }
      } catch (err) {
        console.error(`Failed to fetch midnight energy for ${entityId}:`, err);
      }
    }
  }, [isConnected, settings.entities.equipment, fetchHistory]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void fetchMidnightEnergies();
    }, 0);
    const interval = setInterval(fetchMidnightEnergies, 60 * 60 * 1000);
    return () => {
      window.clearTimeout(timeout);
      clearInterval(interval);
    };
  }, [fetchMidnightEnergies]);

  // Fetch mini sparkline history for dashboard cards
  const fetchDashboardHistory = useCallback(async () => {
    if (!isConnected || (activeTab !== 'live')) return;
    const entityIds: string[] = [];

    if ((settings.dashboard.liveStatsView as string) === 'sparkline') {
      const tankEntities = Object.values(settings.entities.tank).filter(Boolean);
      const roomEntities = settings.entities.room ? Object.values(settings.entities.room).filter(Boolean) : [];
      const customEntities = settings.customSensors?.map(s => s.haKey).filter(Boolean) || [];
      entityIds.push(...tankEntities, ...roomEntities, ...customEntities);
    }

    const historyData: Record<string, DataPoint[]> = {};

    for (const entityId of entityIds) {
      try {
        const data = await fetchHistory(entityId, 24);
        if (data) {
          historyData[entityId] = historyResponseToPoints(data, entityId, {
            rangeHours: 24,
            currentState: entities?.[entityId]?.state,
          });
        }
      } catch (err) {
        console.error(`Failed to fetch history for ${entityId}:`, err);
      }
    }

    setDashboardHistory(historyData);
  }, [isConnected, activeTab, settings.dashboard.liveStatsView, settings.entities.tank, settings.entities.room, settings.customSensors, entities, fetchHistory]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void fetchDashboardHistory();
    }, 0);
    const interval = setInterval(fetchDashboardHistory, 15 * 60 * 1000);
    return () => {
      window.clearTimeout(timeout);
      clearInterval(interval);
    };
  }, [fetchDashboardHistory]);

  // Fetch tasks for monitoring
  const fetchTasks = useCallback(async () => {
    try {
      const res = await apiFetch('/api/tasks');
      const data = await res.json() as { authenticated?: boolean; tasks?: ReefTask[] };
      if (data.authenticated) {
        setTasks(data.tasks ?? []);
      }
    } catch (err) {
      console.error('Failed to fetch tasks:', err);
    }
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void fetchTasks();
    }, 0);
    const interval = setInterval(fetchTasks, 15 * 60 * 1000);
    return () => {
      window.clearTimeout(timeout);
      clearInterval(interval);
    };
  }, [fetchTasks]);

  // Get entity states safely
  const getEntityState = (entityId: string | undefined) => entityId ? entities?.[entityId]?.state : undefined;

  // Mode switching logic
  const handleModeSwitch = useCallback((modeId: string, equipmentConfig: Record<string, EquipmentModeState>, duration?: number) => {
    if (!isConnected) return;

    updateNestedSetting('general', { activeMode: modeId });

    if (duration && duration > 0) {
      const expiry = Date.now() + (duration * 60 * 1000);
      setActiveModeExpiry(expiry);
    } else {
      setActiveModeExpiry(null);
    }

    Object.entries(equipmentConfig || {}).forEach(([equipKey, state]) => {
      if (state === 'ignore') return;
      const equipConfig = settings.entities.equipment[equipKey];
      if (equipConfig && equipConfig.switch) {
        if (state === 'on') {
          turnOnSwitch(equipConfig.switch);
        } else if (state === 'off') {
          turnOffSwitch(equipConfig.switch);
        }
      }
    });
  }, [isConnected, settings.entities.equipment, updateNestedSetting, setActiveModeExpiry, turnOnSwitch, turnOffSwitch]);

  // Listener for programmatic mode changes
  useEffect(() => {
    const handleProgrammaticModeChange = (event: Event) => {
      if (!(event instanceof CustomEvent)) return;
      const { modeId, equipmentConfig } = event.detail as {
        modeId?: string;
        equipmentConfig?: Record<string, EquipmentModeState>;
      };
      if (!modeId || !equipmentConfig) return;
      handleModeSwitch(modeId, equipmentConfig);
    };
    window.addEventListener('reef_mode_change', handleProgrammaticModeChange);
    return () => window.removeEventListener('reef_mode_change', handleProgrammaticModeChange);
  }, [handleModeSwitch]);

  // Card click handlers
  const handleCardClick = (id: string, label: string, color: string = '#00b4d8', isManual: boolean = false) => {
    setSelectedParam({ id, label, color, isManual });
  };

  const handleEquipmentClick = (label: string, entityId: string, icon: React.ReactNode) => {
    setSelectedEquipment({ label, entityId, icon });
  };

  return (
    <div className={styles.dashboardContainer}>
      <header className={styles.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          {/* eslint-disable-next-line @next/next/no-img-element -- Ingress path is only known in the browser. */}
          <img suppressHydrationWarning src={logoSrc} alt="OpenReef Logo" width={64} height={64} style={{ height: '64px', width: 'auto' }} />
          <div>
            <h1 className={styles.title}>{settings.general.tankName}</h1>
            <p style={{ color: '#778da9', margin: '0.25rem 0 0 0' }}>{settings.general.userName}&apos;s OpenReef</p>
          </div>
        </div>
        <button
          type="button"
          className={styles.statusIndicator}
          title={isConnected ? 'HA Connected' : error || 'Connecting to HA... Click to retry.'}
          onClick={() => { void reconnect(); }}
        >
          <div className={`${styles.statusDot} ${isConnected ? styles.connected : styles.disconnected}`} />
          <span className={styles.statusText}>{isConnected ? 'HA Connected' : error || 'Connecting to HA...'}</span>
        </button>
      </header>

      <nav className={styles.navBar}>
        <button
          className={`${styles.tabButton} ${activeTab === 'mission' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('mission')}
        >
          <Shield size={20} />
          <span>Mission Control</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'live' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('live')}
        >
          <Activity size={20} />
          <span>Live Stats</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'manual' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('manual')}
        >
          <Activity size={20} />
          <span>Manual Tests</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'controls' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('controls')}
        >
          <Zap size={20} />
          <span>Controls</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'lights' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('lights')}
        >
          <Lightbulb size={20} />
          <span>Lights</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'waves' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('waves')}
        >
          <Waves size={20} />
          <span>OSW</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'energy' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('energy')}
        >
          <Activity size={20} />
          <span>Energy</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'tasks' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('tasks')}
        >
          <ClipboardList size={20} />
          <span>Tasks</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'spawning' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('spawning')}
        >
          <Waves size={20} />
          <span>Spawning</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'guardian' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('guardian')}
        >
          <Shield size={20} />
          <span>Guardian</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'reports' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('reports')}
        >
          <FileText size={20} />
          <span>Reports</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'analytics' ? styles.activeTab : ''}`}
          onClick={() => setActiveTab('analytics')}
        >
          <TrendingUp size={20} />
          <span>Analytics</span>
        </button>
        <button
          onClick={() => setActiveTab('water-change')}
          className={`${styles.tabButton} ${activeTab === 'water-change' ? styles.activeTab : ''}`}
        >
          <Droplets size={18} />
          <span>Water Change</span>
        </button>
        <button
          onClick={() => setActiveTab('diagram')}
          className={`${styles.tabButton} ${activeTab === 'diagram' ? styles.activeTab : ''}`}
        >
          <Layout size={18} />
          <span>Diagram</span>
        </button>
        <button
          onClick={() => setActiveTab('camera')}
          className={`${styles.tabButton} ${activeTab === 'camera' ? styles.activeTab : ''}`}
        >
          <Video size={18} />
          <span>Camera</span>
        </button>
        <button
          className={`${styles.tabButton} ${activeTab === 'settings' ? styles.activeTab : ''}`}
          onClick={() => { setSettingsDeepLink(null); setActiveTab('settings'); }}
        >
          <Settings size={20} />
          <span>Settings</span>
        </button>
      </nav>

      {/* ─── Tab Content ─── */}

      {activeTab === 'mission' && (
        <MissionControlScreen
          tasks={tasks}
          setTasks={setTasks}
          setActiveTab={setActiveTab as (tab: string) => void}
          setSettingsDeepLink={setSettingsDeepLink}
        />
      )}

      {activeTab === 'live' && (
        <LiveStatsScreen
          onCardClick={handleCardClick}
          dashboardHistory={dashboardHistory}
        />
      )}

      {activeTab === 'manual' && (
        <ManualStatsScreen onCardClick={handleCardClick} />
      )}

      {activeTab === 'controls' && (
        <section className={styles.grid}>
          <h2 className={styles.sectionTitle}>Controls</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '1.5rem', gridColumn: '1 / -1' }}>
            {Object.entries(settings.entities.equipment).map(([key, config]) => (
              <EntitySwitch
                key={key}
                label={getEquipmentName(key, key)}
                state={getEntityState(config.switch)}
                onToggle={() => toggleSwitch(config.switch)}
                onClick={() => handleEquipmentClick(getEquipmentName(key, key), config.switch, <Zap size={24} />)}
                icon={<Zap size={20} />}
              />
            ))}
          </div>
        </section>
      )}

      {activeTab === 'lights' && <LightsScreen />}

      {activeTab === 'waves' && <OceanSeaWavesScreen />}

      {activeTab === 'energy' && (
        <EnergyScreen
          midnightEnergies={midnightEnergies}
          onEquipmentClick={handleEquipmentClick}
        />
      )}

      {activeTab === 'tasks' && <TasksScreen />}
      {activeTab === 'spawning' && <SpawningScreen />}
      {activeTab === 'guardian' && <GuardianScreen />}
      {activeTab === 'reports' && <ReportsScreen tasks={tasks} />}
      {activeTab === 'analytics' && <AnalyticsScreen />}
      {activeTab === 'water-change' && <WaterChangeScreen />}
      {activeTab === 'diagram' && <ReefDiagramScreen />}
      {activeTab === 'camera' && <CameraScreen setActiveTab={setActiveTab as (tab: string) => void} />}

      {activeTab === 'settings' && (
        <SettingsScreen
          initialSection={settingsDeepLink?.section}
          initialEditingAlarmId={settingsDeepLink?.alarmId}
          key={settingsDeepLink ? `${settingsDeepLink.section}-${settingsDeepLink.alarmId}` : 'default'}
        />
      )}

      {/* ─── System Modes (always visible) ─── */}
      <section className={styles.grid}>
        <h2 className={styles.sectionTitle}>System Modes</h2>
        <div className={styles.card} style={{ gridColumn: 'span 1' }}>
          <h3 style={{ margin: '0 0 1rem 0', color: '#e0e1dd', fontSize: '1.2rem' }}>System Modes</h3>
          <div className={styles.modeGrid} style={{ gridTemplateColumns: '1fr' }}>
            {settings.modes?.map((mode) => (
              <button
                key={mode.id}
                className={styles.controlButton}
                style={{
                  borderColor: settings.general.activeMode === mode.id ? settings.general.themeColor : '#27272a',
                  color: settings.general.activeMode === mode.id ? settings.general.themeColor : 'inherit',
                  justifyContent: 'flex-start',
                  paddingLeft: '1.5rem'
                }}
                onClick={() => handleModeSwitch(mode.id, mode.equipmentConfig, mode.duration)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  {mode.id === 'camera' ? <Activity size={20} /> :
                    mode.id.includes('feed') ? <Coffee size={20} /> :
                      mode.id === 'maintenance' ? <Shield size={20} /> :
                        mode.id === 'running' ? <Zap size={20} /> : <Power size={20} />}
                  <span>{mode.label}</span>
                  {settings.general.activeMode === mode.id && activeModeExpiry && (
                    <div style={{
                      marginLeft: 'auto',
                      marginRight: '1rem',
                      fontSize: '0.75rem',
                      padding: '2px 8px',
                      background: 'rgba(var(--primary-rgb), 0.1)',
                      borderRadius: '4px',
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}>
                      <Clock size={12} />
                      {(() => {
                        const remaining = Math.max(0, activeModeExpiry - Date.now());
                        const mins = Math.floor(remaining / 60000);
                        const secs = Math.floor((remaining % 60000) / 1000);
                        return `${mins}:${secs.toString().padStart(2, '0')}`;
                      })()}
                    </div>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Modals ─── */}
      {selectedParam && (
        <ParamHistoryModal
          selectedParam={selectedParam}
          onClose={() => setSelectedParam(null)}
        />
      )}

      {selectedEquipment && (
        <EquipmentDetailModal
          selectedEquipment={selectedEquipment}
          onClose={() => setSelectedEquipment(null)}
        />
      )}

      {/* ─── Maintenance Banner ─── */}
      {getEntityState(settings.entities.modes.maintenance) === 'on' && (
        <div style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          background: '#fbbf24',
          color: '#000',
          padding: '0.5rem',
          textAlign: 'center',
          fontWeight: 'bold',
          zIndex: 100
        }}>
          MAINTENANCE MODE ACTIVE - SOME AUTOMATIONS MAY BE DISABLED
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  return (
    <SettingsProvider>
      <DashboardContent />
    </SettingsProvider>
  );
}
