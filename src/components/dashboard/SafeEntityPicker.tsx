'use client';

import React, { useState } from 'react';
import styles from '@/app/dashboard.module.css';
import { getLocalEntitySuggestions } from '@/lib/local-entity-suggestions';
import type { EntitySuggestionTarget } from '@/lib/entity-suggestions';
import type { OpenReefEntityCandidate } from '@/types/reef';

type SafeEntityPickerProps = {
    label: string;
    value: string;
    target: EntitySuggestionTarget;
    placeholder?: string;
    onChange: (entityId: string) => void;
};

export const SafeEntityPicker: React.FC<SafeEntityPickerProps> = ({
    label,
    value,
    target,
    placeholder,
    onChange,
}) => {
    const [isSearching, setIsSearching] = useState(false);
    const [candidates, setCandidates] = useState<OpenReefEntityCandidate[]>([]);
    const [error, setError] = useState<string | null>(null);

    const handleSearch = () => {
        setIsSearching(true);
        setError(null);
        setCandidates(getLocalEntitySuggestions(target, value, placeholder));
        setIsSearching(false);
    };

    return (
        <div className={styles.entityPicker}>
            <label className={styles.label}>{label}</label>
            <input
                type="text"
                className={styles.input}
                placeholder={placeholder}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                autoComplete="off"
            />
            <div className={styles.entitySuggestionRow}>
                <button
                    type="button"
                    className={styles.entityFindButton}
                    onClick={handleSearch}
                    disabled={isSearching}
                >
                    {isSearching ? 'Finding matches...' : 'Show safe suggestions'}
                </button>
            </div>
            {error && <p className={styles.entityPickerHint}>{error}</p>}
            {candidates.length > 0 && (
                <div className={styles.entitySuggestionRow}>
                    {candidates.map((candidate) => (
                        <button
                            key={candidate.entity_id}
                            type="button"
                            className={`${styles.entitySuggestionButton} ${value === candidate.entity_id ? styles.activeEntitySuggestion : ''}`}
                            onClick={() => onChange(candidate.entity_id)}
                            title={candidate.entity_id}
                        >
                            <span>{candidate.name}</span>
                            <code>{candidate.entity_id}</code>
                        </button>
                    ))}
                </div>
            )}
            {!isSearching && candidates.length === 0 && !error && (
                <p className={styles.entityPickerHint}>Choose a match or paste an entity ID.</p>
            )}
        </div>
    );
};
