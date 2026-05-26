import 'server-only';

import path from 'path';

export const getOpenReefDataDir = () => {
    if (process.env.OPENREEF_DATA_DIR) return process.env.OPENREEF_DATA_DIR;
    if (process.env.HA_ADDON_MODE === 'true') return '/data';
    return process.cwd();
};

export const getOpenReefDataPath = (filename: string) => (
    path.join(getOpenReefDataDir(), filename)
);
