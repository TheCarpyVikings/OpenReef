import { GoogleGenerativeAI, type GenerativeModel } from "@google/generative-ai";

export const LAGERTHA_PROMPT = `
You are Lagertha, a legendary Viking shieldmaiden and the fierce guardian of OpenReef. 
Your tone is strong, authoritative, and direct, yet deeply protective of the life within the reef tank.
You refer to the reef inhabitants as "the shoal" or "our subjects" and the tank as "the realm."
Use Viking-themed terminology: 
- Success/Stability = "The gods smile upon us," "The seas are calm."
- Crises/Alerts = "A storm approaches!", "Prepare for battle!", "The Kraken stirs!"
- Equipment = "The great pumps," "The life-fires (heaters)."
- Instructions = "By Odin's eye," "Hearken to my words."

Always check the current system state provided to you. If there are critical alerts or overdue tasks, warn the user immediately with urgency.
Keep your responses relatively concise but filled with character. You are here to serve as an AI Guardian.
`;

export interface SystemStatus {
    alerts: string[];
    warnings: string[];
    overdueTasks: string[];
    sensorReadings: Record<string, { value: string; unit: string; range?: string; isIssue?: boolean }>;
}

export class AIService {
    private genAI: GoogleGenerativeAI;
    private model: GenerativeModel;

    constructor(apiKey: string) {
        this.genAI = new GoogleGenerativeAI(apiKey);
        // Using gemini-2.5-flash as requested by the user
        this.model = this.genAI.getGenerativeModel({ model: "gemini-2.5-flash" });
    }

    private formatStatusPrompt(status: SystemStatus): string {
        let prompt = "\n\nCURRENT STATUS OF THE REALM:\n";

        if (status.alerts.length > 0) {
            prompt += "CRITICAL ALERTS: " + status.alerts.join(", ") + "\n";
        }
        if (status.warnings.length > 0) {
            prompt += "WARNINGS: " + status.warnings.join(", ") + "\n";
        }
        if (status.overdueTasks.length > 0) {
            prompt += "OVERDUE TASKS: " + status.overdueTasks.join(", ") + "\n";
        }

        prompt += "SENSOR READINGS:\n";
        for (const [key, data] of Object.entries(status.sensorReadings)) {
            prompt += `- ${key}: ${data.value}${data.unit} ${data.range ? `(Range: ${data.range})` : ""} ${data.isIssue ? "!! ERROR !!" : ""}\n`;
        }

        return prompt;
    }

    async getResponse(userInput: string, status: SystemStatus): Promise<string> {
        try {
            const systemPrompt = LAGERTHA_PROMPT + this.formatStatusPrompt(status);
            const chat = this.model.startChat({
                history: [
                    {
                        role: "user",
                        parts: [{ text: systemPrompt }],
                    },
                    {
                        role: "model",
                        parts: [{ text: "The realm is safe under my watch. What is your command, Shieldbrother?" }],
                    },
                ],
            });

            const result = await chat.sendMessage(userInput);
            const response = await result.response;
            return response.text();
        } catch (error) {
            console.error("Gemini Error:", error);
            return "The gods have clouded my vision! (Error connecting to Gemini)";
        }
    }
}
