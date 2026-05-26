'use client';

import React, { useState, useMemo } from 'react';
import {
    CheckCircle2, Circle, Plus, RefreshCw, Trash2, Tag,
    Calendar as CalendarIcon, List as ListIcon, ChevronLeft, ChevronRight,
    Clock, Edit2, X, Save
} from 'lucide-react';
import { useSettings } from '@/context/SettingsContext';
import { apiFetch, withIngressPath } from '@/lib/api-fetch';
import styles from '@/app/dashboard.module.css';
import type { ReefTask, TaskPriority } from '@/types/reef';

const CATEGORIES = ['General', 'Maintenance', 'Testing', 'Dosing'];
const PRIORITIES: TaskPriority[] = ['Low', 'Medium', 'High'];

export const TasksScreen: React.FC = () => {
    const { settings, updateRecurringTaskLastGenerated } = useSettings();
    const [tasks, setTasks] = useState<ReefTask[]>([]);
    const [viewMode, setViewMode] = useState<'list' | 'calendar'>('list');

    // New Task Form State
    const [newTaskTitle, setNewTaskTitle] = useState('');
    const [newTaskCategory, setNewTaskCategory] = useState('General');
    const [newTaskPriority, setNewTaskPriority] = useState<'Low' | 'Medium' | 'High'>('Medium');
    const [newTaskDue, setNewTaskDue] = useState('');
    const [newTaskNotes, setNewTaskNotes] = useState('');

    const [isSyncing, setIsSyncing] = useState(false);
    const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
    const [listId, setListId] = useState<string | null>(null);
    const [listTitle, setListTitle] = useState<string | null>(null);

    // Editing State
    const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
    const [editTaskTitle, setEditTaskTitle] = useState('');
    const [editTaskCategory, setEditTaskCategory] = useState('General');
    const [editTaskPriority, setEditTaskPriority] = useState<'Low' | 'Medium' | 'High'>('Medium');
    const [editTaskDue, setEditTaskDue] = useState('');
    const [editTaskNotes, setEditTaskNotes] = useState('');


    // Calendar state
    const [currentDate, setCurrentDate] = useState(new Date());

    const fetchTasks = async () => {
        setIsSyncing(true);
        try {
            const res = await apiFetch('/api/tasks');
            const data = await res.json();
            setIsAuthenticated(data.authenticated);
            if (data.authenticated) {
                setTasks(data.tasks);
                setListId(data.listId);
                setListTitle(data.listTitle);
            }
        } catch (err) {
            console.error('Failed to fetch tasks:', err);
        } finally {
            setIsSyncing(false);
        }
    };

    React.useEffect(() => {
        fetchTasks();
    }, []);

    // Check for recurring tasks
    React.useEffect(() => {
        if (isAuthenticated === null || (isAuthenticated && !listId)) return;

        const checkRecurring = async () => {
            const now = Date.now();
            const OneDayMs = 24 * 60 * 60 * 1000;

            for (const rTask of settings.tasks.recurring) {
                const lastGen = rTask.lastGenerated || 0;
                const intervalMs = rTask.intervalDays * OneDayMs;

                if (rTask.startDate && now < new Date(rTask.startDate).getTime()) continue;

                if (now - lastGen >= intervalMs) {
                    const tempId = Math.random().toString(36).substr(2, 9);
                    const newTask: ReefTask = {
                        id: tempId,
                        title: rTask.title,
                        completed: false,
                        category: rTask.category,
                        priority: 'Medium',
                        due: new Date().toISOString().split('T')[0]
                    };

                    setTasks(prev => [newTask, ...prev]);

                    if (isAuthenticated && listId) {
                        try {
                            await apiFetch('/api/tasks', {
                                method: 'POST',
                                body: JSON.stringify({
                                    action: 'insert',
                                    title: rTask.title,
                                    listId,
                                    category: rTask.category,
                                    priority: 'Medium',
                                    due: newTask.due
                                }),
                            });
                        } catch (e) {
                            console.error('Failed to sync generated task', e);
                        }
                    }
                    updateRecurringTaskLastGenerated(rTask.id, now);
                }
            }
        };

        if (settings.tasks.recurring.length > 0) checkRecurring();
    }, [settings.tasks.recurring, isAuthenticated, listId, updateRecurringTaskLastGenerated]);

    const toggleTask = async (id: string, completed: boolean) => {
        setTasks(tasks.map(t => t.id === id ? { ...t, completed: !completed } : t));

        if (isAuthenticated) {
            try {
                await apiFetch('/api/tasks', {
                    method: 'POST',
                    body: JSON.stringify({ action: 'update', taskId: id, listId, completed: !completed }),
                });
            } catch (err) {
                console.error('Failed to update task:', err);
            }
        }
    };

    const addTask = async () => {
        if (!newTaskTitle.trim()) return;

        const tempId = Math.random().toString(36).substr(2, 9);
        const finalTitle = newTaskPriority === 'High' ? newTaskTitle.toUpperCase() : newTaskTitle;

        const newTask: ReefTask = {
            id: tempId,
            title: finalTitle,
            completed: false,
            category: newTaskCategory,
            priority: newTaskPriority,
            due: newTaskDue || undefined,
            notes: newTaskNotes || undefined
        };

        setTasks([newTask, ...tasks]);
        setNewTaskTitle('');
        setNewTaskDue('');
        setNewTaskNotes('');

        if (isAuthenticated) {
            try {
                const res = await apiFetch('/api/tasks', {
                    method: 'POST',
                    body: JSON.stringify({
                        action: 'insert',
                        title: finalTitle,
                        listId,
                        category: newTaskCategory,
                        priority: newTaskPriority,
                        due: newTaskDue,
                        notes: newTaskNotes
                    }),
                });
                const result = await res.json();
                setTasks(prev => prev.map(t => t.id === tempId ? { ...t, id: result.id } : t));
            } catch (err) {
                console.error('Failed to add task:', err);
            }
        }
    };

    const deleteTask = async (id: string) => {
        setTasks(tasks.filter(t => t.id !== id));
        if (isAuthenticated && listId) {
            try {
                await apiFetch('/api/tasks', {
                    method: 'POST',
                    body: JSON.stringify({ action: 'delete', taskId: id, listId }),
                });
            } catch (err) {
                console.error('Failed to delete task:', err);
            }
        }
    };

    const handleSync = () => {
        if (!isAuthenticated) {
            window.location.href = withIngressPath('/api/auth/google');
        } else {
            fetchTasks();
        }
    };

    const startEditing = (task: ReefTask) => {
        setEditingTaskId(task.id);
        setEditTaskTitle(task.title);
        setEditTaskCategory(task.category);
        setEditTaskPriority(task.priority);
        setEditTaskDue(task.due || '');
        setEditTaskNotes(task.notes || '');
    };

    const cancelEditing = () => {
        setEditingTaskId(null);
    };

    const saveTaskEdit = async () => {
        if (!editingTaskId || !editTaskTitle.trim()) return;

        const finalTitle = editTaskPriority === 'High' ? editTaskTitle.toUpperCase() : editTaskTitle;

        // Update local state
        setTasks(prev => prev.map(t => t.id === editingTaskId ? {
            ...t,
            title: finalTitle,
            category: editTaskCategory,
            priority: editTaskPriority,
            due: editTaskDue || undefined,
            notes: editTaskNotes || undefined
        } : t));

        setEditingTaskId(null);

        if (isAuthenticated && listId) {
            try {
                await apiFetch('/api/tasks', {
                    method: 'POST',
                    body: JSON.stringify({
                        action: 'update',
                        taskId: editingTaskId,
                        listId,
                        title: finalTitle,
                        category: editTaskCategory,
                        priority: editTaskPriority,
                        due: editTaskDue,
                        notes: editTaskNotes
                    }),
                });
            } catch (err) {
                console.error('Failed to sync task update:', err);
            }
        }
    };

    // Calendar logic
    const calendarDays = useMemo(() => {
        const year = currentDate.getFullYear();
        const month = currentDate.getMonth();
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);

        const days = [];
        // Pad start
        const startPadding = firstDay.getDay();
        for (let i = startPadding - 1; i >= 0; i--) {
            days.push({
                date: new Date(year, month, -i),
                isCurrentMonth: false
            });
        }

        // Current month
        for (let i = 1; i <= lastDay.getDate(); i++) {
            days.push({
                date: new Date(year, month, i),
                isCurrentMonth: true
            });
        }

        // Pad end
        const endPadding = 42 - days.length;
        for (let i = 1; i <= endPadding; i++) {
            days.push({
                date: new Date(year, month + 1, i),
                isCurrentMonth: false
            });
        }

        return days;
    }, [currentDate]);

    const changeMonth = (offset: number) => {
        const next = new Date(currentDate);
        next.setMonth(next.getMonth() + offset);
        setCurrentDate(next);
    };

    const getTasksForDate = (date: Date) => {
        const dateStr = date.toISOString().split('T')[0];
        return tasks.filter(t => t.due === dateStr);
    };

    const isToday = (date: Date) => {
        const today = new Date();
        return date.getDate() === today.getDate() &&
            date.getMonth() === today.getMonth() &&
            date.getFullYear() === today.getFullYear();
    };

    const renderCalendar = () => (
        <div className={styles.card} style={{ gridColumn: '1 / -1' }}>
            <div className={styles.calendarHeader}>
                <h3 className={styles.calendarTitle}>
                    {currentDate.toLocaleString('default', { month: 'long', year: 'numeric' })}
                </h3>
                <div className={styles.calendarNav}>
                    <button className={styles.navBtn} onClick={() => changeMonth(-1)}><ChevronLeft size={20} /></button>
                    <button className={styles.navBtn} onClick={() => setCurrentDate(new Date())}>Today</button>
                    <button className={styles.navBtn} onClick={() => changeMonth(1)}><ChevronRight size={20} /></button>
                </div>
            </div>

            <div className={styles.calendarGrid}>
                {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => (
                    <div key={d} className={styles.calendarDayHeader}>{d}</div>
                ))}
                {calendarDays.map((day, i) => {
                    const dayTasks = getTasksForDate(day.date);
                    return (
                        <div key={i} className={`
                            ${styles.calendarDay} 
                            ${!day.isCurrentMonth ? styles.otherMonth : ''}
                            ${isToday(day.date) ? styles.today : ''}
                        `}>
                            <span className={styles.dayNumber}>{day.date.getDate()}</span>
                            {dayTasks.map(t => (
                                <div key={t.id} className={`${styles.calendarTask} ${t.completed ? styles.calendarTaskCompleted : ''}`}>
                                    {t.title}
                                </div>
                            ))}
                        </div>
                    );
                })}
            </div>
        </div>
    );

    const renderList = () => (
        <div className={styles.card} style={{ gridColumn: '1 / -1', padding: '1.5rem' }}>
            <div className={styles.addTaskForm} style={{ flexWrap: 'wrap' }}>
                <input
                    type="text"
                    placeholder="What needs to be done?"
                    className={styles.taskInput}
                    value={newTaskTitle}
                    onChange={(e) => setNewTaskTitle(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && addTask()}
                    style={{ flex: '1 1 300px' }}
                />
                <input
                    type="text"
                    placeholder="Details/Notes..."
                    className={styles.taskInput}
                    value={newTaskNotes}
                    onChange={(e) => setNewTaskNotes(e.target.value)}
                    style={{ flex: '1 1 200px' }}
                />
                <select
                    className={styles.taskSelect}
                    value={newTaskCategory}
                    onChange={(e) => setNewTaskCategory(e.target.value)}
                >
                    {CATEGORIES.map(cat => <option key={cat} value={cat}>{cat}</option>)}
                </select>
                <select
                    className={styles.taskSelect}
                    value={newTaskPriority}
                    onChange={(e) => setNewTaskPriority(e.target.value as TaskPriority)}
                >
                    {PRIORITIES.map(p => <option key={p} value={p}>{p} Priority</option>)}
                </select>
                <input
                    type="date"
                    className={styles.taskSelect}
                    value={newTaskDue}
                    onChange={(e) => setNewTaskDue(e.target.value)}
                />
                <button className={styles.addTaskButton} onClick={addTask}>
                    <Plus size={20} />
                </button>
            </div>

            <div className={styles.taskList}>
                {tasks.map((task) => (
                    <div key={task.id} className={`${styles.taskItem} ${task.completed ? styles.taskCompleted : ''}`}>
                        {editingTaskId === task.id ? (
                            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                <div style={{ display: 'flex', gap: '0.5rem' }}>
                                    <input
                                        type="text"
                                        className={styles.taskInput}
                                        value={editTaskTitle}
                                        onChange={(e) => setEditTaskTitle(e.target.value)}
                                        placeholder="Task Title"
                                        style={{ flex: 1 }}
                                    />
                                    <select
                                        className={styles.taskSelect}
                                        value={editTaskPriority}
                                        onChange={(e) => setEditTaskPriority(e.target.value as TaskPriority)}
                                    >
                                        {PRIORITIES.map(p => <option key={p} value={p}>{p} Priority</option>)}
                                    </select>
                                </div>
                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    <select
                                        className={styles.taskSelect}
                                        value={editTaskCategory}
                                        onChange={(e) => setEditTaskCategory(e.target.value)}
                                        style={{ flex: 1 }}
                                    >
                                        {CATEGORIES.map(cat => <option key={cat} value={cat}>{cat}</option>)}
                                    </select>
                                    <input
                                        type="date"
                                        className={styles.taskSelect}
                                        value={editTaskDue}
                                        onChange={(e) => setEditTaskDue(e.target.value)}
                                        style={{ flex: 1 }}
                                    />
                                </div>
                                <textarea
                                    className={styles.taskInput}
                                    value={editTaskNotes}
                                    onChange={(e) => setEditTaskNotes(e.target.value)}
                                    placeholder="Notes/Details..."
                                    style={{ width: '100%', minHeight: '60px', borderRadius: '8px', padding: '0.75rem' }}
                                />
                                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                                    <button className={styles.syncButton} onClick={cancelEditing} title="Cancel" style={{ padding: '0.4rem 0.8rem', backgroundColor: '#3e5c76' }}>
                                        <X size={16} /> Cancel
                                    </button>
                                    <button className={styles.addTaskButton} onClick={saveTaskEdit} title="Save Changes" style={{ padding: '0.4rem 0.8rem' }}>
                                        <Save size={16} /> Save
                                    </button>
                                </div>
                            </div>
                        ) : (
                            <>
                                <button className={styles.taskToggle} onClick={() => toggleTask(task.id, task.completed)}>
                                    {task.completed ? <CheckCircle2 size={24} color="#4ade80" /> : <Circle size={24} />}
                                </button>
                                <div className={styles.taskContent}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                        <span className={styles.taskTitle}>{task.title}</span>
                                        <span className={`${styles.priorityBadge} ${styles['priority' + task.priority]}`}>
                                            {task.priority}
                                        </span>
                                    </div>
                                    <div className={styles.taskMeta}>
                                        <span className={styles.taskCategory}><Tag size={12} /> {task.category}</span>
                                        {task.due && (
                                            <span className={`${styles.taskDueDate} ${new Date(task.due) < new Date() && !task.completed ? styles.overdue : ''}`}>
                                                <Clock size={12} /> {new Date(task.due).toLocaleDateString()}
                                            </span>
                                        )}
                                    </div>
                                    {task.notes && (
                                        <div style={{
                                            fontSize: '0.8rem',
                                            color: '#778da9',
                                            marginTop: '0.25rem',
                                            whiteSpace: 'pre-wrap',
                                            fontStyle: 'italic'
                                        }}>
                                            {task.notes}
                                        </div>
                                    )}
                                </div>
                                <div style={{ display: 'flex', gap: '0.25rem' }}>
                                    <button className={styles.taskDelete} style={{ opacity: 1 }} onClick={() => startEditing(task)} title="Edit Task">
                                        <Edit2 size={18} />
                                    </button>
                                    <button className={styles.taskDelete} style={{ opacity: 1 }} onClick={() => deleteTask(task.id)} title="Delete Task">
                                        <Trash2 size={18} />
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                ))}
                {tasks.length === 0 && (
                    <div className={styles.noData}>
                        <CheckCircle2 size={48} color="#778da9" />
                        <p>All clear! Your reef is in top shape.</p>
                    </div>
                )}
            </div>
        </div>
    );



    return (
        <section className={styles.grid}>
            <div className={styles.tasksHeader}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <h2 className={styles.sectionTitle} style={{ margin: 0 }}>Reef Management</h2>
                    <div className={styles.viewTabs}>
                        <button
                            className={`${styles.viewTab} ${viewMode === 'list' && styles.activeViewTab}`}
                            onClick={() => setViewMode('list')}
                        >
                            <ListIcon size={16} /> List
                        </button>
                        <button
                            className={`${styles.viewTab} ${viewMode === 'calendar' && styles.activeViewTab}`}
                            onClick={() => setViewMode('calendar')}
                        >
                            <CalendarIcon size={16} /> Calendar
                        </button>
                    </div>
                </div>

                <button
                    className={styles.syncButton}
                    onClick={handleSync}
                    disabled={isSyncing}
                >
                    <RefreshCw size={16} className={isSyncing ? styles.spinning : ''} />
                    <span>{isSyncing ? 'Syncing...' : (isAuthenticated ? 'Sync' : 'Connect Google')}</span>
                </button>
            </div>

            {isAuthenticated && (
                <div style={{
                    fontSize: '0.8rem',
                    color: '#778da9',
                    marginBottom: '1rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    padding: '0 0.5rem'
                }}>
                    <CheckCircle2 size={12} color="#4ade80" />
                    Connected to Google Tasks: <span style={{ color: '#e0e1dd', fontWeight: 600 }}>{listTitle || 'Default List'}</span>
                </div>
            )}

            {viewMode === 'list' ? renderList() : renderCalendar()}
        </section>
    );
};
