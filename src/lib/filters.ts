/**
 * Simple Moving Average (SMA)
 */
export function calculateSMA(data: { x: number; y: number }[], windowSize: number): { x: number; y: number }[] {
    if (data.length < windowSize) return data;

    const result: { x: number; y: number }[] = [];
    for (let i = 0; i < data.length; i++) {
        if (i < windowSize - 1) {
            result.push({ x: data[i].x, y: data[i].y });
            continue;
        }

        let sum = 0;
        for (let j = 0; j < windowSize; j++) {
            sum += data[i - j].y;
        }
        result.push({ x: data[i].x, y: sum / windowSize });
    }
    return result;
}

/**
 * Exponential Moving Average (EMA)
 */
export function calculateEMA(data: { x: number; y: number }[], windowSize: number): { x: number; y: number }[] {
    if (data.length === 0) return [];

    const alpha = 2 / (windowSize + 1);
    const result: { x: number; y: number }[] = [{ x: data[0].x, y: data[0].y }];

    for (let i = 1; i < data.length; i++) {
        const lastEma = result[i - 1].y;
        const currentEma = data[i].y * alpha + lastEma * (1 - alpha);
        result.push({ x: data[i].x, y: currentEma });
    }
    return result;
}

/**
 * Savitzky-Golay Filter
 * Smoothes data using local least-squares polynomial approximation.
 * 
 * @param data Input points
 * @param windowSize Size of the window (must be odd)
 * @param derivative Derivative order (0 for smoothing)
 * @param polynomialOrder Polynomial order (usually 2 or 3)
 */
export function calculateSavitzkyGolay(
    data: { x: number; y: number }[],
    windowSize: number,
    polynomialOrder: number = 2
): { x: number; y: number }[] {
    // Ensure window size is odd and at least polyOrder + 1
    if (windowSize % 2 === 0) windowSize++;
    if (windowSize < polynomialOrder + 1) windowSize = polynomialOrder + 1;
    if (windowSize % 2 === 0) windowSize++; // Re-ensure odd if incremented

    if (data.length < windowSize) return data;

    const m = (windowSize - 1) / 2;
    const coeffs = getSavitzkyGolayCoefficients(m, polynomialOrder);

    const result: { x: number; y: number }[] = [];

    for (let i = 0; i < data.length; i++) {
        // Handle edges by just returning original or using smaller window
        // For simplicity in a live graph, we'll just use the original value at edges
        if (i < m || i >= data.length - m) {
            result.push({ x: data[i].x, y: data[i].y });
            continue;
        }

        let smoothedY = 0;
        for (let j = -m; j <= m; j++) {
            smoothedY += coeffs[j + m] * data[i + j].y;
        }
        result.push({ x: data[i].x, y: smoothedY });
    }

    return result;
}

/**
 * Pre-calculates SG coefficients for a given window and order.
 * This is a simplified implementation for small orders.
 */
function getSavitzkyGolayCoefficients(m: number, p: number): number[] {
    // For p=2 or p=3 (they share the same smoothing coefficients)
    // and common window sizes, we can provide optimized versions.
    // However, let's implement the general matrix approach if possible, 
    // or just handle the most common ones.

    // Matrix J (Vandermonde) where J_ij = i^j for i in [-m, m] and j in [0, p]
    const J: number[][] = [];
    for (let i = -m; i <= m; i++) {
        const row: number[] = [];
        for (let j = 0; j <= p; j++) {
            row.push(Math.pow(i, j));
        }
        J.push(row);
    }

    // Coefficients matrix C = (J^T * J)^-1 * J^T
    // We only need the first row of C for smoothing (j=0)
    // C = (J^T * J)^-1 * J^T
    // Let A = J^T * J
    const JT = transpose(J);
    const A = multiply(JT, J);
    const AInv = invert(A);
    const C = multiply(AInv, JT);

    return C[0]; // First row gives smoothing coefficients
}

// Minimal Matrix Utils
function transpose(m: number[][]): number[][] {
    return m[0].map((_, i) => m.map(row => row[i]));
}

function multiply(a: number[][], b: number[][]): number[][] {
    const result: number[][] = [];
    for (let i = 0; i < a.length; i++) {
        result[i] = [];
        for (let j = 0; j < b[0].length; j++) {
            let sum = 0;
            for (let k = 0; k < a[0].length; k++) {
                sum += a[i][k] * b[k][j];
            }
            result[i][j] = sum;
        }
    }
    return result;
}

function invert(m: number[][]): number[][] {
    // Gauss-Jordan elimination for small matrices
    const n = m.length;
    const inv: number[][] = [];
    const temp: number[][] = [];

    for (let i = 0; i < n; i++) {
        inv[i] = [];
        temp[i] = [...m[i]];
        for (let j = 0; j < n; j++) {
            inv[i][j] = (i === j) ? 1 : 0;
        }
    }

    for (let i = 0; i < n; i++) {
        let pivot = temp[i][i];
        if (pivot === 0) {
            // Find a non-zero pivot
            for (let k = i + 1; k < n; k++) {
                if (temp[k][i] !== 0) {
                    [temp[i], temp[k]] = [temp[k], temp[i]];
                    [inv[i], inv[k]] = [inv[k], inv[i]];
                    pivot = temp[i][i];
                    break;
                }
            }
        }

        for (let j = 0; j < n; j++) {
            temp[i][j] /= pivot;
            inv[i][j] /= pivot;
        }

        for (let k = 0; k < n; k++) {
            if (k !== i) {
                const factor = temp[k][i];
                for (let j = 0; j < n; j++) {
                    temp[k][j] -= factor * temp[i][j];
                    inv[k][j] -= factor * inv[i][j];
                }
            }
        }
    }

    return inv;
}
