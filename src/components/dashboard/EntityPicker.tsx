import React, { useId, useMemo } from 'react';
import type { HassEntities } from 'home-assistant-js-websocket';
import styles from '@/app/dashboard.module.css';
import { EntitySuggestionTarget, getEntitySuggestions } from '@/lib/entity-suggestions';

type EntityPickerProps = {
    value: string;
    onChange: (entityId: string) => void;
    entities: HassEntities | null;
    target: EntitySuggestionTarget;
    placeholder?: string;
};

export const EntityPicker: React.FC<EntityPickerProps> = ({
    value,
    onChange,
    entities,
    target,
    placeholder,
}) => {
    const listId = useId();
    const suggestions = useMemo(
        () => getEntitySuggestions(entities, target, 5),
        [entities, target],
    );

    return (
        <div className={styles.entityPicker}>
            <input
                type="text"
                className={styles.input}
                list={listId}
                placeholder={placeholder}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                autoComplete="off"
            />
            <datalist id={listId}>
                {suggestions.map((suggestion) => (
                    <option key={suggestion.entityId} value={suggestion.entityId}>
                        {suggestion.label}
                    </option>
                ))}
            </datalist>
            {suggestions.length > 0 && (
                <div className={styles.entitySuggestionRow}>
                    {suggestions.slice(0, 3).map((suggestion) => (
                        <button
                            key={suggestion.entityId}
                            type="button"
                            className={`${styles.entitySuggestionButton} ${value === suggestion.entityId ? styles.activeEntitySuggestion : ''}`}
                            onClick={() => onChange(suggestion.entityId)}
                            title={suggestion.entityId}
                        >
                            <span>{suggestion.label}</span>
                            <code>{suggestion.entityId}</code>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
};
