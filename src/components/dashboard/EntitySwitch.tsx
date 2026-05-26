import React from 'react';
import styles from '@/app/dashboard.module.css';
import { Power, Activity } from 'lucide-react';

interface EntitySwitchProps {
    label: string;
    state: string | undefined;
    onToggle: (e: React.MouseEvent) => void;
    onClick: () => void;
    icon?: React.ReactNode;
}

export const EntitySwitch: React.FC<EntitySwitchProps> = ({ label, state, onToggle, onClick, icon }) => {
    const isOn = state === 'on';

    return (
        <div
            className={`${styles.card} ${styles.clickable} ${isOn ? styles.activeCard : ''}`}
            onClick={onClick}
        >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: 0, flex: 1 }}>
                    <div className={styles.iconWrapper} style={{ flexShrink: 0 }}>
                        {icon || <Activity size={20} />}
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                        <div className={styles.sensorLabel} style={{ marginBottom: '0.25rem' }}>Equipment</div>
                        <div style={{
                            fontWeight: 600,
                            fontSize: '1.125rem',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis'
                        }} title={label}>
                            {label}
                        </div>
                    </div>
                </div>
                <button
                    className={`${styles.toggleButton} ${isOn ? styles.toggleOn : ''}`}
                    onClick={(e) => {
                        e.stopPropagation();
                        onToggle(e);
                    }}
                >
                    <Power size={18} />
                </button>
            </div>
            <div style={{ marginTop: '1rem', display: 'flex', gap: '1rem' }}>
                <div className={styles.miniDetail}>
                    <Activity size={14} />
                    <span>Monitoring Energy</span>
                </div>
            </div>
        </div>
    );
};
