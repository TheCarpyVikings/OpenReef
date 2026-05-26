import { useEffect, useState } from 'react';

export function useNow(refreshMs?: number) {
    const [now, setNow] = useState(0);

    useEffect(() => {
        const update = () => setNow(Date.now());
        const timeout = window.setTimeout(update, 0);
        const interval = refreshMs ? window.setInterval(update, refreshMs) : undefined;

        return () => {
            window.clearTimeout(timeout);
            if (interval !== undefined) window.clearInterval(interval);
        };
    }, [refreshMs]);

    return now;
}
