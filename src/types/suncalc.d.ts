declare module 'suncalc' {
    export type SunTimes = {
        sunrise: Date;
        sunset: Date;
        [key: string]: Date;
    };

    export type MoonIllumination = {
        fraction: number;
        phase: number;
        angle: number;
    };

    const SunCalc: {
        getTimes(date: Date, latitude: number, longitude: number): SunTimes;
        getMoonIllumination(date: Date): MoonIllumination;
    };

    export default SunCalc;
}
