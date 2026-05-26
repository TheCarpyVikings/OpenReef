import { NextResponse } from 'next/server';
import SunCalc from 'suncalc';

export async function GET(request: Request) {
    const { searchParams } = new URL(request.url);
    const latStr = searchParams.get('lat');
    const lonStr = searchParams.get('lon');

    if (!latStr || !lonStr) {
        return NextResponse.json(
            { error: 'Missing lat or lon query parameters' },
            { status: 400 }
        );
    }

    const lat = parseFloat(latStr);
    const lon = parseFloat(lonStr);

    if (isNaN(lat) || isNaN(lon)) {
        return NextResponse.json(
            { error: 'Invalid lat or lon query parameters' },
            { status: 400 }
        );
    }

    const now = new Date();

    // 1. Calculate Sun and Moon data for the location
    const sunTimes = SunCalc.getTimes(now, lat, lon);
    const moonIllumination = SunCalc.getMoonIllumination(now);

    // We get moon phase as a fraction (0.0 to 1.0)
    // Home Assistant's moon component typically uses categorical strings, but fractional 0-1 is more accurate for brightness.
    const moonPhase = moonIllumination.fraction;

    // 2. Fetch Sea Surface Temperature (SST) from NOAA Coral Reef Watch (CRW)
    // We'll use the CoralTemp daily 5km dataset
    let sst = null;
    try {
        // Construct NOAA ERDDAP URL.
        // E.g. https://coastwatch.pfeg.noaa.gov/erddap/griddap/NOAA_DHW.json?CRW_SST[(last)][(lat)][(lon)]
        // Since the user might specify a coordinate slightly off a data point, we must format it carefully or use the nearest neighbor.
        // ERDDAP lets you request nearest neighbor by omitting stride and providing exact target coords inside the brackets.

        // We need to ensure coords are within the dataset bounds (-89.975 to 89.975, -179.975 to 179.975)
        const noaaLat = Math.max(-89.975, Math.min(89.975, lat));
        const noaaLon = Math.max(-179.975, Math.min(179.975, lon));

        const noaaUrl = `https://coastwatch.pfeg.noaa.gov/erddap/griddap/NOAA_DHW.json?CRW_SST[(last)][(${noaaLat})][(${noaaLon})]`;

        const response = await fetch(noaaUrl, { next: { revalidate: 3600 } }); // Cache for 1 hour
        if (response.ok) {
            const data = await response.json();
            if (data?.table?.rows && data.table.rows.length > 0) {
                // The rows array returns: [time, latitude, longitude, CRW_SST]
                sst = data.table.rows[0][3];
            }
        } else {
            console.error('NOAA ERDDAP Error:', response.status, response.statusText);
        }
    } catch (error) {
        console.error('Failed to fetch from NOAA:', error);
    }

    // Format output times as predictable ISO strings
    return NextResponse.json({
        sun: {
            sunrise: sunTimes.sunrise.toISOString(),
            sunset: sunTimes.sunset.toISOString(),
        },
        moon: {
            fraction: moonPhase,
        },
        seaSurfaceTemperature: sst,
        timestamp: now.toISOString(),
    });
}
