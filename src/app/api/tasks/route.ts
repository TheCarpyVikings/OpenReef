import { NextRequest, NextResponse } from 'next/server';
import { listTaskLists, listTasks, insertTask, updateTask, deleteTask, setTokens, TOKEN_PATH } from '@/lib/google-tasks';
import type { GoogleTaskUpdates } from '@/lib/google-tasks';
import type { GoogleCredentials } from '@/lib/google-tasks';
import type { tasks_v1 } from 'googleapis';
import fs from 'fs';
import { z } from 'zod';
import { validateContentType, safeErrorResponse, getErrorMessage } from '@/lib/validation';
import { rateLimit } from '@/lib/rate-limit';
import type { ReefTask, TaskPriority } from '@/types/reef';

const TaskActionSchema = z.object({
    action: z.enum(['insert', 'update', 'delete']),
    title: z.string().max(500).optional(),
    taskId: z.string().optional(),
    listId: z.string().optional(),
    completed: z.boolean().optional(),
    category: z.string().max(100).optional(),
    priority: z.string().max(20).optional(),
    due: z.string().max(20).optional(),
    notes: z.string().max(5000).optional(),
});


const parsePriority = (priority: string | undefined): TaskPriority => {
    if (priority === 'Low' || priority === 'Medium' || priority === 'High') return priority;
    return 'Medium';
};

const parseTaskNotes = (task: tasks_v1.Schema$Task): Pick<ReefTask, 'category' | 'priority' | 'notes'> => {
    let category = 'General';
    let priority: TaskPriority = 'Medium';
    let notes = '';

    if (!task.notes) {
        return { category, priority, notes };
    }

    try {
        const metadata = JSON.parse(task.notes) as Partial<{
            category: string;
            priority: string;
            notes: string;
        }>;
        category = metadata.category || category;
        priority = parsePriority(metadata.priority);
        notes = metadata.notes || '';
    } catch {
        const lines = task.notes.split('\n');
        lines.forEach((line) => {
            const trimmed = line.trim();
            if (trimmed.startsWith('Category:')) {
                category = trimmed.split('Category:')[1].trim();
            } else if (trimmed.startsWith('Priority')) {
                priority = parsePriority(trimmed.split(':')[1]?.trim());
            }
        });

        if (task.notes.includes('---')) {
            notes = task.notes.split('---').slice(1).join('---').trim();
        } else {
            notes = lines
                .filter((line) => !line.trim().startsWith('Category:') && !line.trim().startsWith('Priority:'))
                .join('\n')
                .trim();
        }
    }

    return { category, priority, notes };
};

function loadTokens() {
    if (fs.existsSync(TOKEN_PATH)) {
        const tokens = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf-8')) as GoogleCredentials;
        setTokens(tokens);
        return true;
    }
    return false;
}

export async function GET() {
    if (!loadTokens()) {
        console.log('Google Tasks API: No tokens found');
        return NextResponse.json({ authenticated: false });
    }

    try {
        // We'll look for a list called "Reef Tasks" or use the primary one
        const lists = await listTaskLists();
        console.log(`Google Tasks API: Found ${lists?.length || 0} task lists`);

        const reefList = lists?.find(l => l.title === "Reef Tasks");
        const defaultList = lists?.find(l => l.id === "@default" || l.title === "My Tasks");
        if (reefList) console.log('Google Tasks API: Found "Reef Tasks" list');

        const listToUse = reefList || defaultList || (lists && lists[0]);

        if (!listToUse || !listToUse.id) {
            console.warn('Google Tasks API: No task list found');
            return NextResponse.json({ authenticated: true, tasks: [], listId: null });
        }

        console.log(`Google Tasks API: Using list "${listToUse.title}" (${listToUse.id})`);

        const googleTasks = await listTasks(listToUse.id);

        // Map Google tasks to our internal format
        const tasks: ReefTask[] = googleTasks?.map((t) => {
            const { category, priority, notes } = parseTaskNotes(t);

            return {
                id: t.id || '',
                title: t.title || 'Untitled task',
                completed: t.status === 'completed',
                category,
                priority,
                due: t.due ? t.due.split('T')[0] : undefined,
                notes,
                listId: listToUse.id ?? undefined
            };
        }) || [];

        return NextResponse.json({ authenticated: true, tasks, listId: listToUse.id, listTitle: listToUse.title });
    } catch (error: unknown) {
        if (getErrorMessage(error).includes('invalid_grant')) {
            if (fs.existsSync(TOKEN_PATH)) fs.unlinkSync(TOKEN_PATH);
            return NextResponse.json({ authenticated: false, error: 'Google authentication expired' }, { status: 401 });
        }
        return safeErrorResponse(error, 'Failed to fetch tasks');
    }
}

export async function POST(req: NextRequest) {
    // Rate limit: 30 requests per minute for task mutations
    const rateLimitError = rateLimit('tasks', 30);
    if (rateLimitError) return rateLimitError;

    // Validate Content-Type
    const ctError = validateContentType(req);
    if (ctError) return ctError;

    if (!loadTokens()) {
        return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    try {
        const body = await req.json();
        const parsed = TaskActionSchema.safeParse(body);
        if (!parsed.success) {
            return NextResponse.json({ error: 'Invalid input', details: parsed.error.flatten() }, { status: 400 });
        }

        const { action, title, taskId, listId, completed, category, priority, due, notes } = parsed.data;

        // Capitalize title for High priority tasks
        const finalTitle = priority === 'High' && title ? title.toUpperCase() : (title || '');

        // Prepare notes with metadata
        const notesString = `Category: ${category || 'General'}\nPriority : ${priority || 'Medium'}${notes ? '\n---\n' + notes : ''}`;

        if (action === 'insert') {
            const result = await insertTask(listId!, finalTitle, notesString, due ? `${due}T00:00:00Z` : undefined);
            return NextResponse.json(result);
        } else if (action === 'update') {
            const updates: GoogleTaskUpdates = {};
            if (completed !== undefined) updates.completed = completed;
            if (title !== undefined) updates.title = finalTitle;
            if (category !== undefined || priority !== undefined || notes !== undefined) {
                // If we are updating just notes, we need to know the current category/priority
                // For now, we assume they are provided or we'll use defaults
                updates.notes = notesString;
            }
            if (due !== undefined) updates.due = due ? `${due}T00:00:00Z` : undefined;

            const result = await updateTask(listId!, taskId!, updates);
            return NextResponse.json(result);
        }
        else if (action === 'delete') {
            const result = await deleteTask(listId!, taskId!);
            return NextResponse.json(result);
        }

        return NextResponse.json({ error: 'Invalid action' }, { status: 400 });
    } catch (error: unknown) {
        if (getErrorMessage(error).includes('invalid_grant')) {
            if (fs.existsSync(TOKEN_PATH)) fs.unlinkSync(TOKEN_PATH);
            return NextResponse.json({ authenticated: false, error: 'Google authentication expired' }, { status: 401 });
        }
        return safeErrorResponse(error, 'Failed to update task');
    }
}
