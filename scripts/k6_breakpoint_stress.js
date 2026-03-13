import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://10.5.0.71:5008';
const TIMEOUT = __ENV.HTTP_TIMEOUT || '30s';

const scenarioErrors = new Rate('scenario_errors');
const scenarioLatency = new Trend('scenario_latency', true);
const scenarioRequests = new Counter('scenario_requests');

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.12'],
    http_req_duration: ['p(95)<5000', 'p(99)<10000'],
    scenario_errors: ['rate<0.12'],
  },
  scenarios: {
    browse_breakpoint: {
      executor: 'ramping-vus',
      exec: 'browseUser',
      stages: [
        { duration: '1m', target: 15 },
        { duration: '2m', target: 40 },
        { duration: '2m', target: 80 },
        { duration: '2m', target: 120 },
        { duration: '2m', target: 160 },
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '20s',
      tags: { lane: 'browse' },
    },
    dashboard_breakpoint: {
      executor: 'ramping-vus',
      exec: 'dashboardUser',
      stages: [
        { duration: '1m', target: 10 },
        { duration: '2m', target: 25 },
        { duration: '2m', target: 50 },
        { duration: '2m', target: 75 },
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '20s',
      tags: { lane: 'dashboard' },
    },
    live_log_breakpoint: {
      executor: 'ramping-vus',
      exec: 'liveLogUser',
      stages: [
        { duration: '1m', target: 10 },
        { duration: '2m', target: 25 },
        { duration: '2m', target: 50 },
        { duration: '2m', target: 75 },
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '20s',
      tags: { lane: 'live_log' },
    },
    map_graph_breakpoint: {
      executor: 'ramping-vus',
      exec: 'mapGraphUser',
      stages: [
        { duration: '1m', target: 5 },
        { duration: '2m', target: 10 },
        { duration: '2m', target: 20 },
        { duration: '2m', target: 30 },
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '20s',
      tags: { lane: 'map_graph' },
    },
    synchronized_api_spike: {
      executor: 'ramping-arrival-rate',
      exec: 'apiSpikeUser',
      startRate: 5,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 150,
      stages: [
        { duration: '1m', target: 10 },
        { duration: '2m', target: 20 },
        { duration: '2m', target: 35 },
        { duration: '2m', target: 50 },
        { duration: '1m', target: 0 },
      ],
      tags: { lane: 'api_spike' },
    },
  },
};

function get(path, tags = {}) {
  const res = http.get(`${BASE_URL}${path}`, {
    timeout: TIMEOUT,
    tags: { app: 'malla', profile: 'breakpoint-stress', ...tags },
  });

  scenarioRequests.add(1, tags);
  scenarioLatency.add(res.timings.duration, tags);
  scenarioErrors.add(res.status !== 200, tags);

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  return res;
}

export function browseUser() {
  get('/', { page: 'home' });
  get('/nodes', { page: 'nodes' });
  get('/api/nodes/data?limit=100&page=1', { endpoint: 'api_nodes_data' });
  get('/packets', { page: 'packets' });
  get('/api/packets/data?page=1&limit=100', { endpoint: 'api_packets_data' });
  sleep(0.5);
}

export function dashboardUser() {
  get('/dashboard', { page: 'dashboard' });
  get('/api/stats', { endpoint: 'api_stats' });
  get('/api/analytics', { endpoint: 'api_analytics' });
  sleep(5);
}

export function liveLogUser() {
  get('/packets/live', { page: 'live_log' });
  for (let i = 0; i < 6; i += 1) {
    get('/api/packets/live?limit=50', { endpoint: 'api_live_packets' });
    sleep(1);
  }
}

export function mapGraphUser() {
  get('/map', { page: 'map' });
  get('/api/locations', { endpoint: 'api_locations', period: '3d' });
  get('/traceroute-graph', { page: 'traceroute_graph' });
  get('/api/traceroute/graph?hours=72', {
    endpoint: 'api_traceroute_graph',
    period: '72h',
  });
  sleep(3);
}

export function apiSpikeUser() {
  get('/api/stats', { endpoint: 'api_stats_spike' });
  get('/api/analytics', { endpoint: 'api_analytics_spike' });
  get('/api/locations', { endpoint: 'api_locations_spike' });
  get('/api/traceroute/graph?hours=72', {
    endpoint: 'api_traceroute_graph_spike',
  });
  get('/api/packets/live?limit=50', { endpoint: 'api_live_packets_spike' });
}
