import { google } from 'googleapis';
import type { tasks_v1 } from 'googleapis';
import fs from 'fs';
import { getOpenReefDataPath } from '@/lib/server/data-paths';

const CLIENT_ID = process.env.GOOGLE_CLIENT_ID;
const CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET;
const REDIRECT_URI = process.env.GOOGLE_REDIRECT_URI || 'http://localhost:3000/api/auth/callback/google';
export const TOKEN_PATH = getOpenReefDataPath('google-tokens.json');

export const oauth2Client = new google.auth.OAuth2(
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI
);

export type GoogleCredentials = Parameters<typeof oauth2Client.setCredentials>[0];

oauth2Client.on('tokens', (tokens) => {
    if (tokens.refresh_token) {
        console.log('Google API: Received new refresh_token');
    }

    let currentTokens = {};
    if (fs.existsSync(TOKEN_PATH)) {
        try {
            currentTokens = JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf-8'));
        } catch {
            // Ignore parse errors, just overwrite
        }
    }

    const newTokens = { ...currentTokens, ...tokens };
    fs.writeFileSync(TOKEN_PATH, JSON.stringify(newTokens));
    console.log('Google API: Auto-saved updated tokens to disk');
});

export const getAuthUrl = (state?: string) => {
    const scopes = [
        'https://www.googleapis.com/auth/tasks',
        'https://www.googleapis.com/auth/spreadsheets'
    ];
    return oauth2Client.generateAuthUrl({
        access_type: 'offline',
        scope: scopes,
        prompt: 'consent',
        state,
    });
};

export const setTokens = (tokens: GoogleCredentials) => {
    oauth2Client.setCredentials(tokens);
};

export const listTaskLists = async () => {
    const tasks = google.tasks({ version: 'v1', auth: oauth2Client });
    const res = await tasks.tasklists.list();
    return res.data.items;
};

export const listTasks = async (taskListId: string) => {
    const tasks = google.tasks({ version: 'v1', auth: oauth2Client });
    const res = await tasks.tasks.list({
        tasklist: taskListId,
        maxResults: 100,
        showCompleted: true,
        showHidden: true
    });
    return res.data.items;
};

export const insertTask = async (taskListId: string, title: string, notes?: string, due?: string) => {
    const tasks = google.tasks({ version: 'v1', auth: oauth2Client });
    const res = await tasks.tasks.insert({
        tasklist: taskListId,
        requestBody: {
            title,
            notes,
            due,
        },
    });
    return res.data;
};

export type GoogleTaskUpdates = {
    completed?: boolean;
    title?: string;
    notes?: string;
    due?: string;
};

export const updateTask = async (taskListId: string, taskId: string, updates: GoogleTaskUpdates) => {
    const tasks = google.tasks({ version: 'v1', auth: oauth2Client });
    const requestBody: tasks_v1.Schema$Task = {};
    if (updates.completed !== undefined) {
        requestBody.status = updates.completed ? 'completed' : 'needsAction';
    }
    if (updates.title !== undefined) requestBody.title = updates.title;
    if (updates.notes !== undefined) requestBody.notes = updates.notes;
    if (updates.due !== undefined) requestBody.due = updates.due;

    const res = await tasks.tasks.patch({
        tasklist: taskListId,
        task: taskId,
        requestBody,
    });
    return res.data;
};

export const deleteTask = async (taskListId: string, taskId: string) => {
    const tasks = google.tasks({ version: 'v1', auth: oauth2Client });
    await tasks.tasks.delete({
        tasklist: taskListId,
        task: taskId,
    });
    return { success: true };
};
