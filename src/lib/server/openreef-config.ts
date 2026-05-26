import 'server-only';

import fs from 'fs/promises';
import type { AppSettings } from '@/context/SettingsContext';
import { haWebSocketCommand } from './ha-api';
import { getOpenReefDataDir, getOpenReefDataPath } from './data-paths';

type OpenReefConfigResponse = {
    configured?: boolean;
    settings?: Partial<AppSettings> | null;
};

const getFallbackSettingsPath = () => getOpenReefDataPath('openreef-settings.json');

export async function readOpenReefSettings(): Promise<Partial<AppSettings> | null> {
    try {
        const result = await haWebSocketCommand<OpenReefConfigResponse>({
            type: 'openreef/get_config',
        });
        if (result.settings) return result.settings;
    } catch (error) {
        console.warn('[OpenReef] HA integration settings unavailable, using fallback store:', error);
    }

    try {
        const raw = await fs.readFile(getFallbackSettingsPath(), 'utf-8');
        return JSON.parse(raw) as Partial<AppSettings>;
    } catch {
        return null;
    }
}

export async function writeOpenReefSettings(settings: AppSettings) {
    try {
        await haWebSocketCommand<{ success: boolean }>({
            type: 'openreef/update_config',
            settings,
        });
        return { source: 'integration' as const };
    } catch (error) {
        console.warn('[OpenReef] HA integration update failed, using fallback store:', error);
    }

    const settingsPath = getFallbackSettingsPath();
    await fs.mkdir(getOpenReefDataDir(), { recursive: true });
    await fs.writeFile(settingsPath, JSON.stringify(settings, null, 2));
    return { source: 'fallback' as const };
}

export async function validateOpenReefMappings() {
    try {
        return await haWebSocketCommand({
            type: 'openreef/validate_mappings',
        });
    } catch (error) {
        console.warn('[OpenReef] Mapping validation unavailable:', error);
        return null;
    }
}

export async function isEntityControlArmed(entityId: string): Promise<boolean> {
    const settings = await readOpenReefSettings();
    const equipment = settings?.entities?.equipment;

    if (!equipment) return false;

    return Object.values(equipment).some((config) => (
        config.switch === entityId && config.controlEnabled === true
    ));
}
