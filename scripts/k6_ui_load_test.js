import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:5008';
const TIMEOUT = __ENV.HTTP_TIMEOUT || '30s';

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<1500', 'p(99)<3000'],
  },
  scenarios: {
    browse_pages: {
      executor: 'ramping-vus',
      exec: 'browsePages',
      stages: [
        { duration: '2m', target: 10 },
        { duration: '3m', target: 25 },
        { duration: '3m', target: 50 },
        { duration: '2m', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
    dashboard_polling: {
      executor: 'constant-vus',
      exec: 'dashboardUser',
      vus: 5,
      duration: '10m',
    },
    live_log_polling: {
      executor: 'constant-vus',
      exec: 'liveLogUser',
      vus: 5,
      duration: '10m',
    },
    graph_map_users: {
      executor: 'constant-vus',
      exec: 'graphAndMapUser',
      vus: 3,
      duration: '10m',
    },
  },
};

const defaultParams = {
  timeout: TIMEOUT,
  tags: { app: 'malla' },
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
  sleep(1);

  get('/nodes', { page: 'nodes' });
  get('/api/nodes/data?limit=100&page=1', { endpoint: 'api_nodes' });
  sleep(1);

  get('/packets', { page: 'packets' });
  get('/api/packets/data?page=1&limit=100', { endpoint: 'api_packets' });
  sleep(1);

  get('/help', { page: 'help' });
  sleep(1);
}

export function dashboardUser() {
  get('/dashboard', { page: 'dashboard' });
  get('/api/stats', { endpoint: 'api_stats' });
  get('/api/analytics', { endpoint: 'api_analytics' });
  sleep(30);
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
  sleep(5);

  get('/traceroute-graph', { page: 'traceroute_graph' });
  get('/api/traceroute/graph?hours=24', { endpoint: 'api_traceroute_graph' });
  sleep(10);
}
