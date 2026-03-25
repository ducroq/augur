/**
 * Lazy data loader for tab datasets
 * @module data-loader
 */

/**
 * Loads and caches JSON data files from /data/.
 */
export class DataLoader {
    constructor() {
        this.cache = new Map();
    }

    /**
     * Load a single data file, returning cached version if available.
     * @param {string} filename
     * @returns {Promise<Object|null>}
     */
    async loadFile(filename) {
        if (this.cache.has(filename)) {
            return this.cache.get(filename);
        }

        try {
            const resp = await fetch(`/data/${filename}`);
            if (!resp.ok) {
                console.warn(`Failed to load ${filename}: ${resp.status}`);
                return null;
            }
            const data = await resp.json();
            this.cache.set(filename, data);
            return data;
        } catch (err) {
            console.error(`Error loading ${filename}:`, err);
            return null;
        }
    }

    /**
     * Load multiple data files in parallel.
     * @param {string[]} filenames
     * @returns {Promise<Object>} Map of filename -> data
     */
    async loadFiles(filenames) {
        const results = {};
        const promises = filenames.map(async (f) => {
            results[f] = await this.loadFile(f);
        });
        await Promise.all(promises);
        return results;
    }
}
