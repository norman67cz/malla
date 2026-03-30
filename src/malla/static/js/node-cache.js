(function () {
    const CACHE_KEY_PREFIX = 'malla_nodes_cache_v1';
    const CACHE_TTL_MS = 15 * 60 * 1000; // 15 minutes

    // Internal state shared across the page
    let _nodes = null;              // Array of node objects
    let _loaded = false;            // Whether we attempted to load
    let _loadPromise = null;        // Promise that resolves once loading finished

    function getCurrentMqttSourceParam() {
        try {
            const params = new URLSearchParams(window.location.search);
            if (!params.has('mqtt_source')) {
                return '';
            }
            return (params.get('mqtt_source') || '').trim();
        } catch (_err) {
            return '';
        }
    }

    function getCacheKey() {
        const mqttSource = getCurrentMqttSourceParam() || 'default';
        return `${CACHE_KEY_PREFIX}:${mqttSource}`;
    }

    function buildNodesApiUrl(extraParams = {}) {
        const url = new URL('/api/nodes', window.location.origin);
        const mqttSource = getCurrentMqttSourceParam();
        if (mqttSource) {
            url.searchParams.set('mqtt_source', mqttSource);
        }
        Object.entries(extraParams).forEach(([key, value]) => {
            if (value !== undefined && value !== null && value !== '') {
                url.searchParams.set(key, value);
            }
        });
        return `${url.pathname}${url.search}`;
    }

    /**
     * Attempt to restore cached node list from localStorage.
     * Returns the cached array if it exists and is still fresh, otherwise null.
     */
    function _restoreFromLocalStorage() {
        try {
            const raw = localStorage.getItem(getCacheKey());
            if (!raw) return null;

            const parsed = JSON.parse(raw);
            if (!parsed || !Array.isArray(parsed.nodes)) return null;
            if (Date.now() - (parsed.timestamp || 0) > CACHE_TTL_MS) return null; // stale

            return parsed.nodes;
        } catch (err) {
            console.warn('NodeCache: Failed to restore from localStorage:', err);
            return null;
        }
    }

    /**
     * Persist node list to localStorage together with a timestamp.
     */
    function _persistToLocalStorage(nodes) {
        try {
            const payload = { timestamp: Date.now(), nodes };
            localStorage.setItem(getCacheKey(), JSON.stringify(payload));
        } catch (err) {
            // If storage quota exceeded or disabled, fail silently.
            console.warn('NodeCache: Failed to persist to localStorage:', err);
        }
    }

    const NodeCache = {
        /**
         * Load the full node list, restoring from cache if possible.
         * Always returns a Promise which resolves to the array of nodes.
         */
        load() {
            if (_loaded) return Promise.resolve(_nodes || []);
            if (_loadPromise) return _loadPromise;

            _loadPromise = new Promise(async (resolve) => {
                // 1. Try localStorage first
                const cached = _restoreFromLocalStorage();
                if (cached) {
                    _nodes = cached;
                    _loaded = true;
                    resolve(_nodes);
                    return;
                }

                // 2. Fetch from API
                try {
                    const resp = await fetch(buildNodesApiUrl({ limit: 1000 }));
                    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                    const data = await resp.json();
                    _nodes = data.nodes || [];
                    _persistToLocalStorage(_nodes);
                } catch (err) {
                    console.error('NodeCache: Failed to fetch node list:', err);
                    _nodes = [];
                }

                _loaded = true;
                resolve(_nodes);
            });

            return _loadPromise;
        },

        /**
         * Return the node object with the given numeric ID (as number or string).
         * Resolves to null if not found.
         */
        async getNode(nodeId) {
            await this.load();
            const idStr = nodeId.toString();
            const cachedNode = _nodes.find((n) => n.node_id.toString() === idStr) || null;
            if (cachedNode) {
                return cachedNode;
            }

            try {
                const resp = await fetch(`/api/node/${encodeURIComponent(idStr)}/info`);
                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status}`);
                }
                const data = await resp.json();
                if (data && data.node) {
                    this.addNode(data.node);
                    return data.node;
                }
            } catch (err) {
                console.warn(`NodeCache.getNode: fallback fetch failed for ${idStr}`, err);
            }

            return null;
        },

        /**
         * Search nodes (client-side). Returns array matching the query.
         * Matches against long_name, short_name, decimal ID and hex ID (with leading '!').
         * Limit optional.
         */
        async search(query, limit = 20) {
            // If we already have the full list, search locally
            if (_loaded) {
                const lower = query.toLowerCase();
                const results = _nodes.filter((node) => {
                    const nameLong = (node.long_name || '').toLowerCase();
                    const nameShort = (node.short_name || '').toLowerCase();
                    const hexId = `!${node.node_id.toString(16).padStart(8, '0')}`.toLowerCase();
                    const decId = node.node_id.toString();
                    return (
                        nameLong.includes(lower) ||
                        nameShort.includes(lower) ||
                        hexId.includes(lower) ||
                        decId.includes(lower)
                    );
                });
                if (results.length > 0 || !query) {
                    return results.slice(0, limit);
                }
            }

            // If the local cache did not match, perform a focused query to the API.
            try {
                const resp = await fetch(buildNodesApiUrl({
                    search: query,
                    limit,
                }));
                if (resp.ok) {
                    const data = await resp.json();
                    if (Array.isArray(data.nodes)) {
                        // Merge the quick results into our cache for future lookups
                        data.nodes.forEach((n) => {
                            if (n && n.node_id !== undefined) {
                                NodeCache.addNode(n);
                            }
                        });
                        return data.nodes;
                    }
                }
            } catch (err) {
                console.warn('NodeCache.search: fallback API search failed', err);
            }

            // As a last resort, wait for the full load to finish then search
            await this.load();
            return this.search(query, limit);
        },

        /**
         * Return top nodes ordered by packet_count_24h (desc) – used for "popular" list.
         */
        async topByPackets(limit = 20) {
            await this.load();
            const sorted = [..._nodes].sort((a, b) => (b.packet_count_24h || 0) - (a.packet_count_24h || 0));
            return sorted.slice(0, limit);
        },

        /**
         * Return nodes ordered by gateway_packet_count_24h desc.
         */
        async topByGatewayPackets(limit = 20) {
            await this.load();
            const sorted = [..._nodes].sort((a, b) => (b.gateway_packet_count_24h || 0) - (a.gateway_packet_count_24h || 0));
            return sorted.slice(0, limit);
        },

        /**
         * Add/merge a node object into the cache (e.g., after individual API fetch).
         */
        addNode(node) {
            if (!node || typeof node.node_id === 'undefined') return;
            const existingIdx = _nodes ? _nodes.findIndex((n) => n.node_id === node.node_id) : -1;
            if (existingIdx >= 0) {
                _nodes[existingIdx] = { ..._nodes[existingIdx], ...node };
            } else {
                if (!_nodes) _nodes = [];
                _nodes.push(node);
            }
            _persistToLocalStorage(_nodes);
        },
    };

    // Expose globally
    window.NodeCache = NodeCache;

    // Start loading immediately so data is ready when needed
    NodeCache.load();
})();
