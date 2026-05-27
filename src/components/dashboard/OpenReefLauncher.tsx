'use client';

import React, { useState } from 'react';
import dynamic from 'next/dynamic';
import { FlaskConical, Gauge, ShieldCheck } from 'lucide-react';
import styles from '@/app/dashboard.module.css';
import { withIngressPath } from '@/lib/api-fetch';

const LabsDashboardApp = dynamic(() => import('./DashboardApp'), {
  ssr: false,
  loading: () => <SafeLoading label="Loading Labs dashboard..." />,
});

type OpenReefMode = 'launcher' | 'labs';

function SafeLoading({ label }: { label: string }) {
  return (
    <main className={styles.safeLaunchPage}>
      <div className={styles.safeLaunchPanel}>
        <div className={styles.safeLaunchSpinner} />
        <p>{label}</p>
      </div>
    </main>
  );
}

export function OpenReefLauncher() {
  const [mode, setMode] = useState<OpenReefMode>('launcher');
  const logoSrc = withIngressPath('/openreef-logo.png');
  const labsEnabled = process.env.NEXT_PUBLIC_OPENREEF_ENABLE_LABS === 'true';

  if (mode === 'labs' && labsEnabled) {
    return <LabsDashboardApp />;
  }

  return (
    <main className={styles.safeLaunchPage}>
      <section className={styles.safeLaunchPanel}>
        <div className={styles.safeLaunchHeader}>
          {/* eslint-disable-next-line @next/next/no-img-element -- Ingress path is only known in the browser. */}
          <img src={logoSrc} alt="OpenReef Logo" width={72} height={72} />
          <div>
            <h1>OpenReef</h1>
            <p>Labs add-on</p>
          </div>
        </div>

        <div className={styles.safeLaunchNotice}>
          <ShieldCheck size={20} />
          <span>OpenReef Core now runs as a native Home Assistant sidebar panel from the integration. This add-on is optional Labs space for future advanced features.</span>
        </div>

        <div className={styles.safeLaunchActions}>
          <a className={styles.safeLaunchPrimary} href="/openreef">
            <Gauge size={20} />
            <span>Open Native Panel</span>
          </a>
          {labsEnabled && (
            <button type="button" className={styles.safeLaunchSecondary} onClick={() => setMode('labs')}>
              <FlaskConical size={20} />
              <span>Labs Dashboard</span>
            </button>
          )}
          {!labsEnabled && (
            <div className={styles.safeLaunchSecondary} aria-disabled="true">
              <FlaskConical size={20} />
              <span>Labs disabled</span>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
