import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://10.5.0.71:5008';
const TIMEOUT = __ENV.HTTP_TIMEOUT || '30s';

const hotspotErrors = new Rate('hotspot_errors');
const hotspotLatency = new Trend('hotspot_latency', true);
const hotspotRequests = new Counter('hotspot_requests');

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.10'],
    http_req_duration: ['p(95)<4000', 'p(99)<8000'],
    hotspot_errors: ['rate<0.10'],
  },
  scenarios: {
    dashboard_stats: {
      executor: 'ramping-arrival-rate',
      exec: 'dashboardStatsHotspot',
      startRate: 2,
      timeUnit: '1s',
      preAllocatedVUs: 10,
      maxVUs: Number(__ENV.DASHBOARD_STATS_MAX_VUS || 90),
      stages: [
        { duration: '1m', target: 5 },
        { duration: '2m', target: 15 },
        { duration: '2m', target: 30 },
        { duration: '2m', target: 45 },
        { duration: '1m', target: 0 },
      ],
      tags: { hotspot: 'dashboard_stats' },
    },
    dashboard_analytics: {
      executor: 'ramping-arrival-rate',
      exec: 'dashboardAnalyticsHotspot',
      startRate: 2,
      timeUnit: '1s',
      preAllocatedVUs: 10,
      maxVUs: Number(__ENV.DASHBOARD_ANALYTICS_MAX_VUS || 100),
      stages: [
        { duration: '1m', target: 5 },
        { duration: '2m', target: 10 },
        { duration: '2m', target: 20 },
        { duration: '2m', target: 30 },
        { duration: '1m', target: 0 },
      ],
      tags: { hotspot: 'dashboard_analytics' },
    },
    live_log_api: {
      executor: 'constant-arrival-rate',
      exec: 'liveLogHotspot',
      rate: Number(__ENV.LIVE_LOG_RATE || 20),
      timeUnit: '1s',
      duration: __ENV.LIVE_LOG_DURATION || '8m',
      preAllocatedVUs: Number(__ENV.LIVE_LOG_VUS || 30),
      maxVUs: Number(__ENV.LIVE_LOG_MAX_VUS || 180),
      tags: { hotspot: 'live_log' },
    },
    locations_api: {
      executor: 'ramping-arrival-rate',
      exec: 'locationsHotspot',
      startRate: 1,
      timeUnit: '1s',
      preAllocatedVUs: 10,
      maxVUs: Number(__ENV.LOCATIONS_MAX_VUS || 100),
      stages: [
        { duration: '1m', target: 3 },
        { duration: '2m', target: 6 },
        { duration: '2m', target: 10 },
        { duration: '2m', target: 14 },
        { duration: '1m', target: 0 },
      ],
      tags: { hotspot: 'locations' },
    },
    traceroute_graph_api: {
      executor: 'ramping-arrival-rate',
      exec: 'tracerouteGraphHotspot',
      startRate: 1,
      timeUnit: '1s',
      preAllocatedVUs: 10,
      maxVUs: Number(__ENV.TRACEROUTE_GRAPH_MAX_VUS || 100),
      stages: [
        { duration: '1m', target: 3 },
        { duration: '2m', target: 6 },
        { duration: '2m', target: 10 },
        { duration: '2m', target: 14 },
        { duration: '1m', target: 0 },
      ],
      tags: { hotspot: 'traceroute_graph' },
    },
    nodes_data_api: {
      executor: 'ramping-arrival-rate',
      exec: 'nodesDataHotspot',
      startRate: 2,
      timeUnit: '1s',
      preAllocatedVUs: 10,
      maxVUs: Number(__ENV.NODES_DATA_MAX_VUS || 90),
      stages: [
        { duration: '1m', target: 5 },
        { duration: '2m', target: 10 },
        { duration: '2m', target: 20 },
        { duration: '2m', target: 30 },
        { duration: '1m', target: 0 },
      ],
      tags: { hotspot: 'nodes_data' },
    },
    packets_data_api: {
      executor: 'ramping-arrival-rate',
      exec: 'packetsDataHotspot',
      startRate: 2,
      timeUnit: '1s',
      preAllocatedVUs: 10,
      maxVUs: Number(__ENV.PACKETS_DATA_MAX_VUS || 90),
      stages: [
        { duration: '1m', target: 5 },
        { duration: '2m', target: 10 },
        { duration: '2m', target: 20 },
        { duration: '2m', target: 30 },
        { duration: '1m', target: 0 },
      ],
      tags: { hotspot: 'packets_data' },
    },
  },
};

function get(path, tags = {}) {
  const res = http.get(`${BASE_URL}${path}`, {
    timeout: TIMEOUT,
    tags: { app: 'malla', profile: 'hotspot-isolation', ...tags },
  });

  hotspotRequests.add(1, tags);
  hotspotLatency.add(res.timings.duration, tags);
  hotspotErrors.add(res.status !== 200, tags);

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  return res;
}

export function dashboardStatsHotspot() {
  get('/api/stats', { endpoint: 'api_stats' });
  sleep(1);
}

export function dashboardAnalyticsHotspot() {
  get('/api/analytics', { endpoint: 'api_analytics' });
  sleep(1);
}

export function liveLogHotspot() {
  get('/api/packets/live?limit=50', { endpoint: 'api_live_packets' });
}

export function locationsHotspot() {
  get('/api/locations', { endpoint: 'api_locations', period: '3d' });
  sleep(1);
}

export function tracerouteGraphHotspot() {
  get('/api/traceroute/graph?hours=72', {
    endpoint: 'api_traceroute_graph',
    period: '72h',
  });
  sleep(1);
}

export function nodesDataHotspot() {
  get('/api/nodes/data?limit=100&page=1', { endpoint: 'api_nodes_data' });
  sleep(1);
}

export function packetsDataHotspot() {
  get('/api/packets/data?page=1&limit=100', { endpoint: 'api_packets_data' });
  sleep(1);
}
