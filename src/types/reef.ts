export type DataPoint = {
    x: number;
    y: number;
};

export type ManualReading = {
    date: string;
    value: number;
};

export type ManualReadings = Record<string, ManualReading[]>;

export type TaskPriority = 'Low' | 'Medium' | 'High';

export type ReefTask = {
    id: string;
    title: string;
    completed: boolean;
    category: string;
    priority: TaskPriority;
    due?: string;
    notes?: string;
    listId?: string;
};

export type DashboardTab =
    | 'mission'
    | 'live'
    | 'manual'
    | 'controls'
    | 'lights'
    | 'waves'
    | 'energy'
    | 'tasks'
    | 'spawning'
    | 'guardian'
    | 'reports'
    | 'analytics'
    | 'water-change'
    | 'diagram'
    | 'camera'
    | 'settings';

export type EquipmentModeState = 'on' | 'off' | 'ignore';

export type HAHistoryEntry = {
    state?: string;
    s?: string;
    last_changed?: string | number;
    lc?: string | number;
    last_updated?: string | number;
    lu?: string | number;
};

export type HAHistoryResponse = HAHistoryEntry[][] | Record<string, HAHistoryEntry[]>;
