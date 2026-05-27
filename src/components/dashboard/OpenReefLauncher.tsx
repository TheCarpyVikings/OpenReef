'use client';

import React, { useState } from 'react';
import dynamic from 'next/dynamic';
import { ArrowRight, Gauge, Settings, ShieldCheck } from 'lucide-react';
import styles from '@/app/dashboard.module.css';
import { withIngressPath } from '@/lib/api-fetch';

const ControllerLiteApp = dynamic(() => import('./ControllerLiteApp'), {
  ssr: false,
  loading: () => <SafeLoading label="Loading OpenReef..." />,
});

const LabsDashboardApp = dynamic(() => import('./DashboardApp'), {
  ssr: false,
  loading: () => <SafeLoading label="Loading Labs dashboard..." />,
});

type OpenReefMode = 'launcher' | 'setup' | 'dashboard' | 'labs';

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

  if (mode === 'setup') {
    return <ControllerLiteApp initialView="setup" onExit={() => setMode('launcher')} />;
  }

  if (mode === 'dashboard') {
    return <ControllerLiteApp initialView="dashboard" />;
  }

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
            <p>Safe start</p>
          </div>
        </div>

        <div className={styles.safeLaunchNotice}>
          <ShieldCheck size={20} />
          <span>OpenReef starts in controller-lite mode. Home Assistant requests are targeted and capped.</span>
        </div>

        <div className={styles.safeLaunchActions}>
          <button type="button" className={styles.safeLaunchPrimary} onClick={() => setMode('setup')}>
            <Settings size={20} />
            <span>Start Setup</span>
            <ArrowRight size={18} />
          </button>
          <button type="button" className={styles.safeLaunchSecondary} onClick={() => setMode('dashboard')}>
            <Gauge size={20} />
            <span>Open Dashboard</span>
          </button>
          {labsEnabled && (
            <button type="button" className={styles.safeLaunchSecondary} onClick={() => setMode('labs')}>
              <Gauge size={20} />
              <span>Labs Dashboard</span>
            </button>
          )}
        </div>
      </section>
    </main>
  );
}
