'use client';

import React, { useState } from 'react';
import dynamic from 'next/dynamic';
import { ArrowRight, Gauge, Settings, ShieldCheck } from 'lucide-react';
import styles from '@/app/dashboard.module.css';
import { withIngressPath } from '@/lib/api-fetch';

const SetupOnlyApp = dynamic(() => import('./SetupOnlyApp'), {
  ssr: false,
  loading: () => <SafeLoading label="Loading setup..." />,
});

const DashboardApp = dynamic(() => import('./DashboardApp'), {
  ssr: false,
  loading: () => <SafeLoading label="Loading dashboard..." />,
});

type OpenReefMode = 'launcher' | 'setup' | 'dashboard';

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

  if (mode === 'setup') {
    return <SetupOnlyApp onExit={() => setMode('launcher')} />;
  }

  if (mode === 'dashboard') {
    return <DashboardApp />;
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
          <span>OpenReef is starting in a low-load mode. Home Assistant is not queried until you ask for entity discovery.</span>
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
        </div>
      </section>
    </main>
  );
}
