'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { apiFetch } from '@/lib/api-fetch';
import type { EquipmentModeState, ManualReadings } from '@/types/reef';

export interface AppSettings {
    general: {
        tankName: string;
        userName: string;
        themeColor: string;
        activeMode: string | null;
        energyTariff: number;
        haUrl: string;
        haToken: string;
        googleSheetId: string;
    };
    dashboard: {
        liveStatsView: 'numbers' | 'gauges' | 'graphs';
        manualStatsView: 'numbers' | 'gauges' | 'graphs';
        visibleCards: string[];
        trendLineType?: 'sma' | 'ema' | 'savitzky-golay' | 'none';
    };
    labels: Record<string, string>;
    equipment: {
        aliases: Record<string, string>;
    };
    alarms: Record<string, {
        label: string;
        entityId: string;
        okValue: string;
        severity: 'critical' | 'warning';
        description?: string;
    }>;
    tasks: {
        recurring: Array<{
            id: string;
            title: string;
            intervalDays: number;
            category: string;
            startDate?: string;
            lastGenerated?: number;
        }>;
    };
    modes: Array<{
        id: string;
        label: string;
        equipmentConfig: Record<string, EquipmentModeState>;
        duration?: number; // duration in minutes
    }>;
    visuals: {
        yAxisRanges: Record<string, { min: number | null; max: number | null }>;
        trendLines: Record<string, {
            enabled: boolean;
            type: 'sma' | 'ema' | 'savitzky-golay' | 'none';
            windowSize: number;
            polynomialOrder: number;
        }>;
    };
    thresholds: Record<string, { min: number; max: number }>;
    entities: {
        tank: {
            temp: string;
            ph: string;
            salinity: string;
            orp: string;
            do: string;
        };
        room: {
            temp: string;
            co2: string;
            humidity: string;
        };
        equipment: Record<string, {
            switch: string;
            power: string;
            energy: string;
            controlEnabled?: boolean;
            showInDiagram?: boolean;
            diagramPosition?: 'tank' | 'sump' | 'room' | 'light' | 'ato_reservoir' | 'dosing_container' | 'awc_fresh' | 'awc_waste';
        }>;
        modes: {
            maintenance: string;
            feed: string;
        };
        tankMain: {
            power: string;
            energy: string;
        };
        energy: {
            dailyEnergy: string;
            weeklyEnergy: string;
            monthlyEnergy: string;
            dailyCost: string;
            weeklyCost: string;
            monthlyCost: string;
        };
    };
    missionControl: {
        environmentalStats: string[];
        criticalEquipment: string[];
        sectionOrder: string[];
    };
    calibration: Record<string, {
        numPoints: number;
        clear: string;
        p1: string;
        v1: number;
        p2: string;
        v2: number;
        p3: string;
        v3: number;
        calibrationLiveEntity?: string;
    }>;
    customSensors: Array<{
        id: string;
        label: string;
        haKey: string;
        group: 'tank' | 'room' | 'manual';
    }>;
    spawning: {
        profileId: string;
        yearShift: number;
        monthShift: number;
        spawnStrength: number;
        phaseOffset: number;
        tempOffset: number;
        entities: {
            profile: string;
            startDate: string;
            strength: string;
            phaseOffset: string;
            tempOffset: string;
            nextSpawnDate: string;
            moonPhase: string;
            targetTemp: string;
            mainLightPlug?: string;
            moonlightBulb?: string;
            thermostatClimate?: string;
        };
    };
    ai: {
        simliApiKey: string;
        geminiApiKey: string;
        openaiApiKey: string;
        enabled: boolean;
        faceId: string;
    };
    lighting: {
        channels: {
            white: string;
            blue: string;
            royalBlue: string;
            violet: string;
            uv: string;
            red: string;
            green: string;
            moonlight: string;
        };
        presets: Array<{
            id: string;
            name: string;
            values: Record<string, number>;
        }>;
        schedule: Array<{
            time: string;
            values: Record<string, number>;
        }>;
    };
    waterChange: {
        enabled: boolean;
        entities: {
            pumpWaste: string;
            pumpFresh: string;
            pumpWasteShowInDiagram?: boolean;
            pumpWastePosition?: 'awc_waste' | 'room' | 'sump';
            pumpFreshShowInDiagram?: boolean;
            pumpFreshPosition?: 'awc_fresh' | 'room' | 'sump';
            wasteFull: string;
            freshEmpty: string;
            tankHigh: string;
            wasteLevel: string;
            freshLevel: string;
            todayTotal: string;
            weekTotal: string;
            monthTotal: string;
        };
        containers: {
            wasteCapacity: number;
            freshCapacity: number;
        };
        percentagePresets: Array<{
            id: string;
            label: string;
            percentage: number;
            entityId: string;
        }>;
    };
    camera: {
        enabled: boolean;
        cameras: Array<{
            id: string;
            label: string;
            entityId: string;
            streamType: 'mjpeg' | 'webrtc';
            directStreamUrl?: string;
        }>;
    };
}

const DEFAULT_SETTINGS: AppSettings = {
    general: {
        tankName: "OpenReef",
        userName: 'Reece',
        themeColor: '#00b4d8',
        activeMode: null,
        energyTariff: 0.28,
        haUrl: process.env.NEXT_PUBLIC_HA_URL || '',
        haToken: '',
        googleSheetId: '',
    },
    dashboard: {
        liveStatsView: 'numbers',
        manualStatsView: 'numbers',
        visibleCards: ['temp', 'ph', 'salinity', 'orp', 'do', 'alk', 'calc', 'mag', 'nitrate', 'phosphate', 'room_temp', 'co2', 'humidity'],
        trendLineType: 'none',
    },
    equipment: {
        aliases: {},
    },
    alarms: {},
    tasks: {
        recurring: [],
    },
    modes: [
        { id: 'feed_fish', label: 'Feed - Fish', equipmentConfig: {} },
        { id: 'feed_coral', label: 'Feed - Coral', equipmentConfig: {} },
        { id: 'maintenance', label: 'Maintenance', equipmentConfig: {} },
        { id: 'camera', label: 'Camera', equipmentConfig: {} },
        { id: 'running', label: 'Running', equipmentConfig: {} },
    ],
    labels: {
        temp: 'Temperature',
        ph: 'pH Level',
        salinity: 'Salinity',
        orp: 'ORP',
        do: 'Dissolved Oxygen',
        room_temp: 'Room Temp',
        co2: 'CO2 Level',
        humidity: 'Humidity',
        alk: 'Alkalinity',
        calc: 'Calcium',
        mag: 'Magnesium',
        nitrate: 'Nitrate',
        phosphate: 'Phosphate',
        total_power: 'Total Power Load',
        active_devices: 'Active Devices',
        total_daily_energy: 'Total Daily Energy',
        total_daily_cost: 'Total Daily Cost',
        spawning_profile: 'Spawning Profile',
        spawning_strength: 'Spawn Strength',
        spawning_phase_offset: 'Phase Offset',
        spawning_temp_offset: 'Temp Offset',
        light_white: 'White Channel',
        light_blue: 'Blue Channel',
        light_royal_blue: 'Royal Blue Channel',
        light_violet: 'Violet Channel',
        light_uv: 'UV Channel',
        light_red: 'Red Channel',
        light_green: 'Green Channel',
        light_moonlight: 'Moonlight Channel',
    },
    visuals: {
        yAxisRanges: {},
        trendLines: {},
    },
    thresholds: {
        temp: { min: 24.5, max: 27.5 },
        ph: { min: 7.8, max: 8.4 },
        salinity: { min: 32, max: 36 },
        orp: { min: 250, max: 450 },
        do: { min: 5, max: 9 },
        alk: { min: 7, max: 11 },
        calc: { min: 380, max: 460 },
        mag: { min: 1250, max: 1450 },
        nitrate: { min: 0, max: 25 },
        phosphate: { min: 0, max: 0.1 },
        room_temp: { min: 16, max: 28 },
        co2: { min: 350, max: 1200 },
        humidity: { min: 30, max: 70 },
    },
    entities: {
        tank: {
            temp: 'sensor.tank_temperature',
            ph: 'sensor.tank_ph',
            salinity: 'sensor.tank_sg',
            orp: 'sensor.tank_orp',
            do: 'sensor.tank_do',
        },
        room: {
            temp: 'sensor.room_temperature',
            co2: 'sensor.room_co2',
            humidity: 'sensor.room_humidity',
        },
        equipment: {
            ATO: { switch: 'switch.ato_plug', power: 'sensor.ato_power', energy: 'sensor.ato_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'sump' },
            INKBIRD: { switch: 'switch.inkbird_plug', power: 'sensor.inkbird_power', energy: 'sensor.inkbird_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'tank' },
            RETURN_PUMP: { switch: 'switch.return_pump_plug', power: 'sensor.return_pump_power', energy: 'sensor.return_pump_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'sump' },
            DOSING_PUMP: { switch: 'switch.dosing_pump_plug', power: 'sensor.dosing_pump_power', energy: 'sensor.dosing_pump_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'sump' },
            SKIMMER: { switch: 'switch.skimmer_plug', power: 'sensor.skimmer_power', energy: 'sensor.skimmer_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'sump' },
            WAVEMAKERS: { switch: 'switch.wavemakers_plug', power: 'sensor.wavemakers_power', energy: 'sensor.wavemakers_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'tank' },
            HYDRA_EDGE: { switch: 'switch.hydra_edge_plug', power: 'sensor.hydra_edge_power', energy: 'sensor.hydra_edge_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'tank' },
            KESSIL: { switch: 'switch.kessil_plug', power: 'sensor.kessil_power', energy: 'sensor.kessil_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'tank' },
            MAG_STIRRER: { switch: 'switch.mag_stirrer_plug', power: 'sensor.mag_stirrer_power', energy: 'sensor.mag_stirrer_energy', controlEnabled: false, showInDiagram: false, diagramPosition: 'room' },
            AIR_PUMP: { switch: 'switch.air_pump_eheim_plug', power: 'sensor.air_pump_power', energy: 'sensor.air_pump_energy', controlEnabled: false, showInDiagram: false, diagramPosition: 'room' },
            RODI: { switch: 'switch.rodi_plug', power: 'sensor.rodi_power', energy: 'sensor.rodi_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'room' },
            HEATER: { switch: 'switch.heater_plug', power: 'sensor.heater_power', energy: 'sensor.heater_energy', controlEnabled: false, showInDiagram: true, diagramPosition: 'sump' },
        },
        modes: {
            maintenance: 'input_boolean.maintenance_mode',
            feed: 'input_boolean.feed_mode',
        },
        tankMain: {
            power: '',
            energy: '',
        },
        energy: {
            dailyEnergy: '',
            weeklyEnergy: '',
            monthlyEnergy: '',
            dailyCost: '',
            weeklyCost: '',
            monthlyCost: '',
        },
    },
    missionControl: {
        environmentalStats: ['temp', 'ph', 'salinity'],
        criticalEquipment: ['RETURN_PUMP', 'SKIMMER', 'HEATER'],
        sectionOrder: ['alarms', 'chemistry', 'equipment', 'tasks'],
    },
    calibration: {
        ph: {
            numPoints: 3,
            clear: 'button.reef_ph_cal_clear',
            p1: 'button.reef_ph_cal_low_4_00',
            v1: 4.00,
            p2: 'button.reef_ph_cal_mid_7_00',
            v2: 7.00,
            p3: 'button.reef_ph_cal_high_10_00',
            v3: 10.00
        }
    },
    customSensors: [],
    spawning: {
        profileId: 'gbr_cairns',
        yearShift: 0,
        monthShift: 0,
        spawnStrength: 100,
        phaseOffset: 0,
        tempOffset: 0,
        entities: {
            profile: 'input_select.coral_spawning_profile',
            startDate: 'input_datetime.coral_spawn_start',
            strength: 'input_number.coral_spawn_strength',
            phaseOffset: 'input_number.coral_spawn_phase_offset',
            tempOffset: 'input_number.coral_spawn_temp_offset',
            nextSpawnDate: 'sensor.coral_next_spawn_date',
            moonPhase: 'sensor.moon_phase', // existing or new
            targetTemp: 'sensor.coral_target_temperature',
            mainLightPlug: '',
            moonlightBulb: '',
            thermostatClimate: ''
        }
    },
    lighting: {
        channels: {
            white: 'number.reef_light_white',
            blue: 'number.reef_light_blue',
            royalBlue: 'number.reef_light_royal_blue',
            violet: 'number.reef_light_violet',
            uv: 'number.reef_light_uv',
            red: 'number.reef_light_red',
            green: 'number.reef_light_green',
            moonlight: 'number.reef_light_moonlight'
        },
        presets: [
            { id: 'ab_plus', name: 'Coral Lab AB+', values: { white: 24, blue: 100, royalBlue: 100, violet: 100, uv: 100, red: 24, green: 24, moonlight: 0 } },
            { id: 'growth', name: 'Max Growth', values: { white: 50, blue: 100, royalBlue: 100, violet: 100, uv: 100, red: 10, green: 10, moonlight: 0 } },
            { id: 'photo', name: 'Photo Mode', values: { white: 80, blue: 20, royalBlue: 20, violet: 0, uv: 0, red: 30, green: 30, moonlight: 0 } },
        ],
        schedule: [
            { time: '08:00', values: { white: 0, blue: 0, royalBlue: 0, violet: 0, uv: 0, red: 0, green: 0, moonlight: 5 } },
            { time: '10:00', values: { white: 10, blue: 30, royalBlue: 30, violet: 20, uv: 10, red: 5, green: 5, moonlight: 0 } },
            { time: '14:00', values: { white: 50, blue: 100, royalBlue: 100, violet: 80, uv: 60, red: 20, green: 20, moonlight: 0 } },
            { time: '18:00', values: { white: 10, blue: 40, royalBlue: 40, violet: 30, uv: 20, red: 5, green: 5, moonlight: 0 } },
            { time: '21:00', values: { white: 0, blue: 0, royalBlue: 0, violet: 0, uv: 0, red: 0, green: 0, moonlight: 10 } },
            { time: '23:00', values: { white: 0, blue: 0, royalBlue: 0, violet: 0, uv: 0, red: 0, green: 0, moonlight: 0 } },
        ]
    },
    ai: {
        simliApiKey: '',
        geminiApiKey: '',
        openaiApiKey: '',
        enabled: true,
        faceId: 'e6fcd8ff-ceda-4fd9-b4f5-ed07e0220eb4', // Provided by user
    },
    waterChange: {
        enabled: true,
        entities: {
            pumpWaste: 'switch.awc_waste_pump',
            pumpFresh: 'switch.awc_fresh_pump',
            pumpWasteShowInDiagram: true,
            pumpWastePosition: 'awc_waste',
            pumpFreshShowInDiagram: true,
            pumpFreshPosition: 'awc_fresh',
            wasteFull: 'binary_sensor.awc_waste_full',
            freshEmpty: 'binary_sensor.awc_fresh_empty',
            tankHigh: 'binary_sensor.awc_tank_high',
            wasteLevel: 'sensor.awc_waste_level',
            freshLevel: 'sensor.awc_fresh_level',
            todayTotal: 'sensor.awc_today_volume',
            weekTotal: 'sensor.awc_week_volume',
            monthTotal: 'sensor.awc_month_volume',
        },
        containers: {
            wasteCapacity: 25,
            freshCapacity: 25,
        },
        percentagePresets: [
            { id: '1perc', label: '1%', percentage: 1, entityId: 'button.awc_1_percent' },
            { id: '2perc', label: '2%', percentage: 2, entityId: 'button.awc_2_percent' },
            { id: '5perc', label: '5%', percentage: 5, entityId: 'button.awc_5_percent' },
            { id: '10perc', label: '10%', percentage: 10, entityId: 'button.awc_10_percent' },
        ],
    },
    camera: {
        enabled: true,
        cameras: [
            { id: 'main', label: 'Reef Tank', entityId: 'camera.reef_tank', streamType: 'mjpeg' as const },
        ],
    },
};

const isLegacyTankName = (value: string | undefined) => {
    if (!value) return false;
    return /^(ragnar'?s\s*reef|ragnarsreef|ragnars_reef)$/i.test(value.trim());
};

const isLegacyUserName = (value: string | undefined) => {
    if (!value) return false;
    return /^reefyreece$/i.test(value.trim());
};

const migrateLegacyBranding = (settings: AppSettings): AppSettings => ({
    ...settings,
    general: {
        ...settings.general,
        tankName: isLegacyTankName(settings.general?.tankName)
            ? DEFAULT_SETTINGS.general.tankName
            : settings.general.tankName,
        userName: isLegacyUserName(settings.general?.userName)
            ? DEFAULT_SETTINGS.general.userName
            : settings.general.userName,
    },
});

interface SettingsContextType {
    settings: AppSettings;
    updateSettings: (newSettings: Partial<AppSettings>) => void;
    updateNestedSetting: <K extends keyof AppSettings>(section: K, data: Partial<AppSettings[K]>) => void;
    getEquipmentName: (key: string, defaultName: string) => string;
    getLabel: (key: string, defaultName?: string) => string;
    addRecurringTask: (task: Omit<AppSettings['tasks']['recurring'][0], 'id' | 'lastGenerated'>) => void;
    removeRecurringTask: (id: string) => void;
    updateRecurringTaskLastGenerated: (id: string, timestamp: number) => void;
    manualReadings: ManualReadings;
    saveManualReadings: (data: ManualReadings) => void;
    clearManualReadings: () => void;
    updateMode: (modeId: string, updates: Partial<{ label: string; equipmentConfig: Record<string, EquipmentModeState>; duration: number }>) => void;
    addEquipment: (name: string) => void;
    removeEquipment: (key: string) => void;
    addAlarm: (alarm: { label: string; entityId: string; okValue: string; severity: 'critical' | 'warning'; description?: string }) => void;
    updateAlarm: (id: string, updates: Partial<{ label: string; entityId: string; okValue: string; severity: 'critical' | 'warning'; description?: string }>) => void;
    removeAlarm: (id: string) => void;
    addCalibrationSensor: (sensorKey: string, numPoints: number, initialValues?: { v1?: number; v2?: number; v3?: number }) => void;
    removeCalibrationSensor: (id: string) => void;
    updateCalibrationSensor: (id: string, data: Partial<AppSettings['calibration'][string]>) => void;
    addCustomSensor: (sensor: Omit<AppSettings['customSensors'][0], 'id'>) => void;
    removeCustomSensor: (id: string) => void;
    haError: string | null;
    setHaError: (error: string | null) => void;
    resetHAConfig: () => void;
    updateSpawningSetting: (data: Partial<AppSettings['spawning']>) => void;
    activeModeExpiry: number | null;
    setActiveModeExpiry: (expiry: number | null) => void;
    syncManualReadingsWithSheets: () => Promise<void>;
    isSyncing: boolean;
    addAwcPreset: (preset: Omit<AppSettings['waterChange']['percentagePresets'][0], 'id'>) => void;
    removeAwcPreset: (id: string) => void;
}

type SettingsResponse = {
    settings?: Partial<AppSettings>;
};

type SheetReadResponse = {
    values?: unknown[][];
};

type LegacyMode = AppSettings['modes'][number] & {
    equipmentOff?: string[];
};

type LegacyCalibration = Partial<AppSettings['calibration'][string]> & {
    low?: string;
    mid?: string;
    high?: string;
};

const LABS_SERVER_SYNC_ENABLED = process.env.NEXT_PUBLIC_OPENREEF_ENABLE_LABS_SYNC === 'true';

/**
 * Strips sensitive fields (API keys, tokens) before persisting to localStorage.
 * OpenReef Labs keeps settings local unless explicit Labs server sync is enabled.
 */
function sanitizeForStorage(s: AppSettings): AppSettings {
    return {
        ...s,
        general: { ...s.general, haToken: '' },
        ai: { ...s.ai, openaiApiKey: '', geminiApiKey: '', simliApiKey: '' },
    };
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

export const SettingsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
    const [isLoaded, setIsLoaded] = useState(false);
    const [haError, setHaError] = useState<string | null>(null);
    const [manualReadings, setManualReadings] = useState<ManualReadings>({});
    const [isSyncing, setIsSyncing] = useState(false);
    const [activeModeExpiry, setActiveModeExpiry] = useState<number | null>(null);
    const syncInProgress = useRef(false);

    // Load manual readings on mount
    useEffect(() => {
        if (typeof window !== 'undefined') {
            const saved = localStorage.getItem('reef_manual_readings');
            if (saved) {
                try {
                    setManualReadings(JSON.parse(saved) as ManualReadings);
                } catch (e) {
                    console.error("Failed to parse manual readings", e);
                }
            }
        }
    }, []);

    const saveManualReadings = useCallback((data: ManualReadings) => {
        setManualReadings(data);
        if (typeof window !== 'undefined') {
            localStorage.setItem('reef_manual_readings', JSON.stringify(data));
        }
    }, []);

    const clearManualReadings = useCallback(() => {
        setManualReadings({});
        if (typeof window !== 'undefined') {
            localStorage.removeItem('reef_manual_readings');
        }
    }, []);

    const syncManualReadingsWithSheets = useCallback(async () => {
        if (!settings.general.googleSheetId || syncInProgress.current) return;

        syncInProgress.current = true;
        setIsSyncing(true);
        try {
            const response = await apiFetch(`/api/sheets/read?spreadsheetId=${settings.general.googleSheetId}`);
            if (!response.ok) throw new Error('Failed to fetch from Google Sheets');

            const data = await response.json() as SheetReadResponse;
            const rows = data.values;

            if (!rows || rows.length === 0) return;

            // Map sheet labels to IDs dynamically based on current settings
            const manualIds = ['alk', 'calc', 'mag', 'salinity', 'nitrate', 'phosphate'];
            const labelMap: Record<string, string> = {};

            // Standard sensors
            manualIds.forEach(id => {
                const label = settings.labels[id] || (id === 'alk' ? 'Alkalinity' : id === 'calc' ? 'Calcium' : id === 'mag' ? 'Magnesium' : id === 'salinity' ? 'Salinity' : id === 'nitrate' ? 'Nitrate' : id === 'phosphate' ? 'Phosphate' : id);
                labelMap[label] = id;
            });

            // Custom sensors (these map back to their 'custom_xxxxx' ID)
            if (settings.customSensors) {
                settings.customSensors.forEach(sensor => {
                    labelMap[sensor.label] = sensor.id;
                });
            }

            const newManualReadings: ManualReadings = {};

            rows.forEach((row) => {
                if (row.length < 3) return;
                const [dateCell, labelCell, valueCell] = row;
                if (typeof labelCell !== 'string') return;

                const dateStr = String(dateCell ?? '');
                const label = labelCell;
                const value = String(valueCell ?? '');

                // Parse date string robustly (Handle DD/MM/YYYY from Sheets)
                let date: string = dateStr;
                if (dateStr && typeof dateStr === 'string' && dateStr.includes('/')) {
                    const parts = dateStr.split('/');
                    if (parts.length === 3) {
                        const [p1, p2, p3] = parts;
                        if (p3.length === 4) {
                            // Normalize DD/MM/YYYY to YYYY-MM-DD
                            date = `${p3}-${p2.padStart(2, '0')}-${p1.padStart(2, '0')}`;
                        } else if (p1.length === 4) {
                            // Handle YYYY/MM/DD just in case
                            date = `${p1}-${p2.padStart(2, '0')}-${p3.padStart(2, '0')}`;
                        }
                    }
                }

                const normalizedLabel = label.trim().toLowerCase();

                // Find matching paramId
                let paramId = normalizedLabel; // Fallback to label if unmapped
                for (const [l, id] of Object.entries(labelMap)) {
                    // We check if the custom sensor or standard label matches case-insensitively
                    if (l.toLowerCase() === normalizedLabel) {
                        paramId = id;
                        break;
                    }
                }

                const val = parseFloat(value);

                if (!isNaN(val)) {
                    if (!newManualReadings[paramId]) {
                        newManualReadings[paramId] = [];
                    }
                    newManualReadings[paramId].push({
                        date,
                        value: val
                    });
                }
            });

            // Sort each array by date
            Object.keys(newManualReadings).forEach(id => {
                newManualReadings[id].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
            });

            setManualReadings(newManualReadings);
            if (typeof window !== 'undefined') {
                localStorage.setItem('reef_manual_readings', JSON.stringify(newManualReadings));
            }
        } catch (err) {
            console.error('Error syncing manual readings:', err);
        } finally {
            setIsSyncing(false);
            syncInProgress.current = false;
        }
    }, [settings.general.googleSheetId, settings.labels, settings.customSensors]);

    const updateMode = (modeId: string, updates: Partial<{ label: string; equipmentConfig: Record<string, EquipmentModeState>; duration: number }>) => {
        const updatedModes = settings.modes.map(m =>
            m.id === modeId ? { ...m, ...updates } : m
        );
        updateSettings({ modes: updatedModes });
    };

    // Mode Timer Logic
    useEffect(() => {
        if (settings.general.activeMode && activeModeExpiry) {
            const checkTimer = () => {
                const now = Date.now();
                if (now >= activeModeExpiry) {
                    console.log(`[Mode Timer] Mode ${settings.general.activeMode} expired. Reverting to running.`);

                    // Revert to running mode
                    updateNestedSetting('general', { activeMode: 'running' });
                    setActiveModeExpiry(null);

                    // Apply running mode config if it exists
                    const runningMode = settings.modes.find(m => m.id === 'running');
                    if (runningMode) {
                        // We need access to HA functions here, but they are in useHomeAssistant
                        // SettingsContext should probably just handle the state, 
                        // and page.tsx or a separate hook should handle the HA side.
                        // However, we'll trigger a custom event or let the dashboard handle it via useEffect.
                        window.dispatchEvent(new CustomEvent('reef_mode_change', {
                            detail: { modeId: 'running', equipmentConfig: runningMode.equipmentConfig }
                        }));
                    }
                }
            };

            const interval = setInterval(checkTimer, 1000);
            return () => clearInterval(interval);
        }
    }, [settings.general.activeMode, activeModeExpiry, settings.modes]);

    // Handle initial load of activeMode and set expiry if needed
    // Actually, it's better to let the UI set the expiry when the mode is clicked.

    useEffect(() => {
        const loadInitialSettings = async () => {
            let initialSettings: AppSettings = { ...DEFAULT_SETTINGS };

            // 0. Fetch non-sensitive HA metadata from the server.
            if (LABS_SERVER_SYNC_ENABLED) {
                try {
                    const haConfigRes = await apiFetch('/api/ha/config');
                    if (haConfigRes.ok) {
                        const haConfig = await haConfigRes.json() as { token?: string; url?: string };
                        if (haConfig.url) {
                            initialSettings.general.haUrl = haConfig.url;
                        }
                    }
                } catch (err) {
                    console.warn('[Settings] Could not fetch HA config from server:', err);
                }
            }

            if (LABS_SERVER_SYNC_ENABLED) {
                try {
                    const response = await apiFetch('/api/settings');
                    const data = await response.json() as SettingsResponse;
                    if (data.settings) {
                        console.log('[Settings] Loaded from server');
                        initialSettings = { ...initialSettings, ...data.settings } as AppSettings;
                    } else {
                        const saved = localStorage.getItem('reefSettings');
                        if (saved) {
                            console.log('[Settings] Server empty, loaded from local storage');
                            const parsed = JSON.parse(saved) as Partial<AppSettings>;
                            initialSettings = { ...initialSettings, ...parsed } as AppSettings;

                            apiFetch('/api/settings', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ settings: initialSettings })
                            }).catch(err => console.error('[Settings] Initial upload failed:', err));
                        }
                    }
                } catch (err) {
                    console.error('[Settings] Server sync failed, using local storage fallback:', err);
                    const saved = localStorage.getItem('reefSettings');
                    if (saved) {
                        const parsed = JSON.parse(saved) as Partial<AppSettings>;
                        initialSettings = { ...initialSettings, ...parsed } as AppSettings;
                    }
                }
            } else {
                const saved = localStorage.getItem('reefSettings');
                if (saved) {
                    const parsed = JSON.parse(saved) as Partial<AppSettings>;
                    initialSettings = { ...initialSettings, ...parsed } as AppSettings;
                }
            }

            initialSettings = migrateLegacyBranding(initialSettings);

            // Migration & Merging Logic
            // Merge modes: ensure ALL default modes exist, and migrate equipmentOff to equipmentConfig
            const savedModes: LegacyMode[] = Array.isArray(initialSettings.modes) ? initialSettings.modes : [];
            const mergedModes = [...savedModes].map((mode) => {
                // Migration: if equipmentOff exists but equipmentConfig doesn't
                if (mode.equipmentOff && !mode.equipmentConfig) {
                    const equipmentConfig: Record<string, EquipmentModeState> = {};
                    mode.equipmentOff.forEach((key) => {
                        equipmentConfig[key] = 'off';
                    });
                    return { ...mode, equipmentConfig };
                }
                return { ...mode, equipmentConfig: mode.equipmentConfig || {} };
            });

            DEFAULT_SETTINGS.modes.forEach(defaultMode => {
                const existingIndex = mergedModes.findIndex(m => m.id === defaultMode.id);
                if (existingIndex === -1) {
                    mergedModes.push(defaultMode);
                }
            });

            // Extra safety: ensure 'running' is definitely there
            if (!mergedModes.find(m => m.id === 'running')) {
                mergedModes.push({ id: 'running', label: 'Running', equipmentConfig: {} });
            }

            // Final state update
            const finalCustomSensors = initialSettings.customSensors || DEFAULT_SETTINGS.customSensors;
            const coreSensorIds = ['temp', 'ph', 'salinity', 'orp', 'do', 'room_temp', 'co2', 'humidity', 'alk', 'calc', 'mag', 'nitrate', 'phosphate'];
            const customSensorIds = (finalCustomSensors || []).map((sensor) => sensor.id);
            const allValidSensorIds = [...coreSensorIds, ...customSensorIds];
            const initialMissionControl = initialSettings.missionControl || DEFAULT_SETTINGS.missionControl;

            setSettings({
                ...DEFAULT_SETTINGS,
                ...initialSettings,
                general: { ...DEFAULT_SETTINGS.general, ...initialSettings.general },
                dashboard: {
                    ...DEFAULT_SETTINGS.dashboard,
                    ...initialSettings.dashboard,
                    visibleCards: (initialSettings.dashboard?.visibleCards || DEFAULT_SETTINGS.dashboard.visibleCards).filter(id => allValidSensorIds.includes(id))
                },
                equipment: { ...DEFAULT_SETTINGS.equipment, ...initialSettings.equipment },
                tasks: { ...DEFAULT_SETTINGS.tasks, ...initialSettings.tasks },
                modes: mergedModes,
                visuals: { ...DEFAULT_SETTINGS.visuals, ...initialSettings.visuals },
                thresholds: { ...DEFAULT_SETTINGS.thresholds, ...initialSettings.thresholds },
                entities: { ...DEFAULT_SETTINGS.entities, ...initialSettings.entities },
                labels: { ...DEFAULT_SETTINGS.labels, ...initialSettings.labels },
                alarms: initialSettings.alarms || DEFAULT_SETTINGS.alarms,
                missionControl: {
                    ...initialMissionControl,
                    environmentalStats: (initialMissionControl.environmentalStats || []).filter(id => allValidSensorIds.includes(id)),
                    sectionOrder: initialMissionControl.sectionOrder || DEFAULT_SETTINGS.missionControl.sectionOrder,
                },
                customSensors: finalCustomSensors,
                calibration: (() => {
                    const cal = { ...(initialSettings.calibration || DEFAULT_SETTINGS.calibration) };
                    Object.keys(cal).forEach(key => {
                        const legacy = cal[key] as LegacyCalibration;
                        if (legacy.low && !legacy.p1) {
                            cal[key] = {
                                numPoints: 3,
                                clear: legacy.clear || '',
                                p1: legacy.low,
                                v1: 4.00,
                                p2: legacy.mid || '',
                                v2: 7.00,
                                p3: legacy.high || '',
                                v3: 10.00
                            };
                        }
                    });
                    return cal;
                })(),
                spawning: { ...DEFAULT_SETTINGS.spawning, ...initialSettings.spawning },
                ai: { ...DEFAULT_SETTINGS.ai, ...initialSettings.ai },
                waterChange: {
                    ...DEFAULT_SETTINGS.waterChange,
                    ...initialSettings.waterChange,
                    entities: { ...DEFAULT_SETTINGS.waterChange.entities, ...initialSettings.waterChange?.entities },
                    containers: { ...DEFAULT_SETTINGS.waterChange.containers, ...initialSettings.waterChange?.containers },
                    percentagePresets: initialSettings.waterChange?.percentagePresets || DEFAULT_SETTINGS.waterChange.percentagePresets
                },
                camera: {
                    ...DEFAULT_SETTINGS.camera,
                    ...initialSettings.camera,
                    cameras: initialSettings.camera?.cameras || DEFAULT_SETTINGS.camera.cameras,
                },
            });

            setIsLoaded(true);
        };

        loadInitialSettings();
    }, []);

    useEffect(() => {
        if (isLoaded) {
            // Sanitize settings before storing in localStorage (strip secrets)
            const sanitized = sanitizeForStorage(settings);
            localStorage.setItem('reefSettings', JSON.stringify(sanitized));

            if (LABS_SERVER_SYNC_ENABLED) {
                apiFetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ settings })
                }).catch(err => console.error('[Settings] Failed to sync to server:', err));
            }

            // Apply theme color globally
            const hex = settings.general.themeColor;
            document.documentElement.style.setProperty('--primary-color', hex);

            // Calculate RGB for rgba() usage
            const r = parseInt(hex.slice(1, 3), 16);
            const g = parseInt(hex.slice(3, 5), 16);
            const b = parseInt(hex.slice(5, 7), 16);
            document.documentElement.style.setProperty('--primary-rgb', `${r}, ${g}, ${b}`);
        }
    }, [settings, isLoaded]);

    const updateSettings = (newSettings: Partial<AppSettings>) => {
        setSettings(prev => ({ ...prev, ...newSettings }));
    };

    const updateNestedSetting = <K extends keyof AppSettings>(section: K, data: Partial<AppSettings[K]>) => {
        setSettings(prev => ({
            ...prev,
            [section]: {
                ...prev[section],
                ...data
            }
        }));
    };

    const resetHAConfig = () => {
        if (!LABS_SERVER_SYNC_ENABLED) {
            updateNestedSetting('general', { haUrl: '', haToken: '' });
            setHaError(null);
            return;
        }

        apiFetch('/api/ha/config').then(res => res.json()).then(config => {
            updateNestedSetting('general', { haUrl: config.url || '', haToken: '' });
        }).catch(() => {
            updateNestedSetting('general', { haUrl: '', haToken: '' });
        });
        setHaError(null);
    };

    const updateSpawningSetting = useCallback((data: Partial<AppSettings['spawning']>) => {
        setSettings(prev => ({
            ...prev,
            spawning: {
                ...prev.spawning,
                ...data
            }
        }));
    }, []);

    const addAwcPreset = useCallback((preset: Omit<AppSettings['waterChange']['percentagePresets'][0], 'id'>) => {
        const newPreset = {
            ...preset,
            id: Math.random().toString(36).substr(2, 9)
        };
        setSettings(prev => ({
            ...prev,
            waterChange: {
                ...prev.waterChange,
                percentagePresets: [...prev.waterChange.percentagePresets, newPreset]
            }
        }));
    }, []);

    const removeAwcPreset = useCallback((id: string) => {
        setSettings(prev => ({
            ...prev,
            waterChange: {
                ...prev.waterChange,
                percentagePresets: prev.waterChange.percentagePresets.filter(p => p.id !== id)
            }
        }));
    }, []);

    if (!isLoaded) {
        return null; // or a loading spinner
    }

    const getEquipmentName = (key: string, defaultName: string) => {
        return settings.equipment.aliases[key] || defaultName;
    };

    const getLabel = (key: string, defaultName?: string) => {
        const custom = settings.customSensors?.find(s => s.id === key);
        if (custom) return custom.label;
        return settings.labels[key] || defaultName || key;
    };

    // Recurring Task Helpers
    const addRecurringTask = (task: Omit<AppSettings['tasks']['recurring'][0], 'id' | 'lastGenerated'>) => {
        const newTask = {
            ...task,
            id: Math.random().toString(36).substr(2, 9),
            lastGenerated: 0 // EPOCH 0 means it will generate immediately if logic checks > interval
        };
        updateNestedSetting('tasks', {
            recurring: [...settings.tasks.recurring, newTask]
        });
    };

    const removeRecurringTask = (id: string) => {
        updateNestedSetting('tasks', {
            recurring: settings.tasks.recurring.filter(t => t.id !== id)
        });
    };

    const updateRecurringTaskLastGenerated = (id: string, timestamp: number) => {
        const updated = settings.tasks.recurring.map(t =>
            t.id === id ? { ...t, lastGenerated: timestamp } : t
        );
        updateNestedSetting('tasks', { recurring: updated });
    };

    const addEquipment = (name: string) => {
        const key = name.toUpperCase().replace(/\s+/g, '_');
        if (settings.entities.equipment[key]) return; // Avoid duplicates

        const newEquipment = {
            ...settings.entities.equipment,
            [key]: { switch: '', power: '', energy: '', controlEnabled: false, showInDiagram: false, diagramPosition: 'room' as const }
        };

        const newAliases = {
            ...settings.equipment.aliases,
            [key]: name
        };

        // Initialize in all modes as 'off'
        const newModes = settings.modes.map(mode => ({
            ...mode,
            equipmentConfig: {
                ...mode.equipmentConfig,
                [key]: 'off' as const
            }
        }));

        setSettings(prev => ({
            ...prev,
            equipment: { ...prev.equipment, aliases: newAliases },
            entities: { ...prev.entities, equipment: newEquipment },
            modes: newModes
        }));
    };

    const removeEquipment = (key: string) => {
        const newEquipment = { ...settings.entities.equipment };
        delete newEquipment[key];

        const newAliases = { ...settings.equipment.aliases };
        delete newAliases[key];

        // Clean up modes
        const newModes = settings.modes.map(mode => {
            const newConfig = { ...mode.equipmentConfig };
            delete newConfig[key];
            return { ...mode, equipmentConfig: newConfig };
        });

        setSettings(prev => ({
            ...prev,
            equipment: { ...prev.equipment, aliases: newAliases },
            entities: { ...prev.entities, equipment: newEquipment },
            modes: newModes
        }));
    };

    const addAlarm = (alarm: { label: string; entityId: string; okValue: string; severity: 'critical' | 'warning'; description?: string }) => {
        const id = 'ALARM_' + Math.random().toString(36).substr(2, 9).toUpperCase();
        setSettings(prev => ({
            ...prev,
            alarms: { ...prev.alarms, [id]: alarm }
        }));
    };

    const updateAlarm = (id: string, updates: Partial<{ label: string; entityId: string; okValue: string; severity: 'critical' | 'warning'; description?: string }>) => {
        setSettings(prev => ({
            ...prev,
            alarms: {
                ...prev.alarms,
                [id]: { ...prev.alarms[id], ...updates }
            }
        }));
    };

    const removeAlarm = (id: string) => {
        const newAlarms = { ...settings.alarms };
        delete newAlarms[id];
        setSettings(prev => ({ ...prev, alarms: newAlarms }));
    };

    const addCalibrationSensor = (sensorKey: string, numPoints: number, initialValues?: { v1?: number; v2?: number; v3?: number }) => {
        setSettings(prev => ({
            ...prev,
            calibration: {
                ...prev.calibration,
                [sensorKey]: {
                    numPoints,
                    clear: '',
                    p1: '',
                    v1: initialValues?.v1 ?? 0,
                    p2: '',
                    v2: initialValues?.v2 ?? 0,
                    p3: '',
                    v3: initialValues?.v3 ?? 0,
                    calibrationLiveEntity: ''
                }
            }
        }));
    };

    const removeCalibrationSensor = (id: string) => {
        const newCal = { ...settings.calibration };
        delete newCal[id];
        setSettings(prev => ({ ...prev, calibration: newCal }));
    };

    const updateCalibrationSensor = (id: string, data: Partial<AppSettings['calibration'][string]>) => {
        setSettings(prev => ({
            ...prev,
            calibration: {
                ...prev.calibration,
                [id]: { ...prev.calibration[id], ...data }
            }
        }));
    };



    return (
        <SettingsContext.Provider value={{
            settings,
            updateSettings,
            updateNestedSetting,
            getEquipmentName,
            getLabel,
            addRecurringTask,
            removeRecurringTask,
            updateRecurringTaskLastGenerated,
            manualReadings,
            saveManualReadings,
            clearManualReadings,
            updateMode,
            activeModeExpiry,
            setActiveModeExpiry,
            addEquipment,
            removeEquipment,
            addAlarm,
            updateAlarm,
            removeAlarm,
            addCalibrationSensor,
            removeCalibrationSensor,
            updateCalibrationSensor,
            addCustomSensor: (sensor) => {
                const id = 'custom_' + Math.random().toString(36).substr(2, 9);
                const updatedSensors = [...(settings.customSensors || []), { ...sensor, id }];
                setSettings(prev => ({ ...prev, customSensors: updatedSensors }));
            },
            removeCustomSensor: (id) => {
                setSettings(prev => ({
                    ...prev,
                    customSensors: (prev.customSensors || []).filter(s => s.id !== id),
                    dashboard: {
                        ...prev.dashboard,
                        visibleCards: (prev.dashboard?.visibleCards || []).filter(cid => cid !== id)
                    },
                    missionControl: {
                        ...prev.missionControl,
                        environmentalStats: (prev.missionControl?.environmentalStats || []).filter(sid => sid !== id)
                    }
                }));
            },
            haError,
            setHaError,
            resetHAConfig,
            updateSpawningSetting,
            syncManualReadingsWithSheets,
            isSyncing,
            addAwcPreset,
            removeAwcPreset
        }}>
            {children}
        </SettingsContext.Provider>
    );
};

export const useSettings = () => {
    const context = useContext(SettingsContext);
    if (context === undefined) {
        throw new Error('useSettings must be used within a SettingsProvider');
    }
    return context;
};
