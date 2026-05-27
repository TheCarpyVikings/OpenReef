'use client';

import { SettingsProvider } from '@/context/SettingsContext';
import { SetupWizard } from './SetupWizard';

type SetupOnlyAppProps = {
  onExit?: () => void;
};

export default function SetupOnlyApp({ onExit }: SetupOnlyAppProps) {
  return (
    <SettingsProvider>
      <SetupWizard onComplete={onExit || (() => undefined)} />
    </SettingsProvider>
  );
}
