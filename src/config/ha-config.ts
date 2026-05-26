const isAddonMode = process.env.HA_ADDON_MODE === 'true';

export const HA_CONFIG = {
    BASE_URL: isAddonMode
        ? 'http://supervisor/core'
        : (process.env.NEXT_PUBLIC_HA_URL || 'http://192.168.1.100:8123'),
    ACCESS_TOKEN: '', // Token is now loaded from server via /api/ha/config — do not hardcode here
    IS_ADDON: isAddonMode,
};
