import { google } from 'googleapis';
import { oauth2Client } from './google-tasks';

export type SheetCellValue = string | number | boolean | null;
export type SheetRow = SheetCellValue[];

export const appendToSheet = async (spreadsheetId: string, range: string, values: SheetRow[]) => {
    const sheets = google.sheets({ version: 'v4', auth: oauth2Client });
    const res = await sheets.spreadsheets.values.append({
        spreadsheetId,
        range,
        valueInputOption: 'RAW',
        requestBody: {
            values,
        },
    });
    return res.data;
};

export const readSheetData = async (spreadsheetId: string, range: string) => {
    const sheets = google.sheets({ version: 'v4', auth: oauth2Client });
    const res = await sheets.spreadsheets.values.get({
        spreadsheetId,
        range,
    });
    return res.data.values;
};
