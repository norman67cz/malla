import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://10.5.0.71:5008';
const TIMEOUT = __ENV.HTTP_TIMEOUT || '30s';

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<2500', 'p(99)<5000'],
  },
  scenarios: {
    browse_pages: {
      executor: 'ramping-vus',
      exec: 'browsePages',
      stages: [
        { duration: '1m', target: 20 },
        { duration: '2m', target: 50 },
        { duration: '3m', target: 100 },
        { duration: '3m', target: 150 },
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '20s',
    },
    dashboard_polling: {
      executor: 'constant-vus',
      exec: 'dashboardUser',
      vus: 20,
      duration: '10m',
    },
    live_log_polling: {
      executor: 'constant-vus',
      exec: 'liveLogUser',
      vus: 20,
      duration: '10m',
    },
    graph_map_users: {
      executor: 'constant-vus',
      exec: 'graphAndMapUser',
      vus: 10,
      duration: '10m',
    },
    api_burst: {
      executor: 'ramping-arrival-rate',
      exec: 'apiBurstUser',
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { duration: '2m', target: 20 },
        { duration: '3m', target: 40 },
        { duration: '2m', target: 60 },
        { duration: '1m', target: 0 },
      ],
    },
  },
};

const defaultParams = {
  timeout: TIMEOUT,
  tags: { app: 'malla', profile: 'aggressive' },
};

function get(path, tags = {}) {
  const res = http.get(`${BASE_URL}${path}`, {
    ...defaultParams,
    tags: { ...defaultParams.tags, ...tags },
  });

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  return res;
}

export function browsePages() {
  get('/', { page: 'home' });
  get('/nodes', { page: 'nodes' });
  get('/api/nodes/data?limit=100&page=1', { endpoint: 'api_nodes' });
  sleep(0.5);

  get('/packets', { page: 'packets' });
  get('/api/packets/data?page=1&limit=100', { endpoint: 'api_packets' });
  sleep(0.5);

  get('/help', { page: 'help' });
  sleep(0.5);
}

export function dashboardUser() {
  get('/dashboard', { page: 'dashboard' });
  get('/api/stats', { endpoint: 'api_stats' });
  get('/api/analytics', { endpoint: 'api_analytics' });
  sleep(10);
}

export function liveLogUser() {
  get('/packets/live', { page: 'live_log' });

  for (let i = 0; i < 10; i += 1) {
    get('/api/packets/live?limit=50', { endpoint: 'api_live_packets' });
    sleep(1);
  }
}

export function graphAndMapUser() {
  get('/map', { page: 'map' });
  get('/api/locations', { endpoint: 'api_locations' });
  sleep(3);

  get('/traceroute-graph', { page: 'traceroute_graph' });
  get('/api/traceroute/graph?hours=24', { endpoint: 'api_traceroute_graph' });
  sleep(5);
}

export function apiBurstUser() {
  get('/api/stats', { endpoint: 'api_stats_burst' });
  get('/api/analytics', { endpoint: 'api_analytics_burst' });
  get('/api/packets/live?limit=50', { endpoint: 'api_live_packets_burst' });
  get('/api/locations', { endpoint: 'api_locations_burst' });
  sleep(1);
}
