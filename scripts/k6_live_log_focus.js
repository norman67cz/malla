import http from 'k6/http';
import { check } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://10.5.0.71:5008';
const TIMEOUT = __ENV.HTTP_TIMEOUT || '30s';

const liveLogErrors = new Rate('live_log_errors');
const liveLogLatency = new Trend('live_log_latency', true);

export const options = {
  thresholds: {
    http_req_failed: ['rate<0.10'],
    http_req_duration: ['p(95)<4000', 'p(99)<8000'],
    live_log_errors: ['rate<0.10'],
  },
  scenarios: {
    live_log_api: {
      executor: 'ramping-arrival-rate',
      exec: 'liveLogHotspot',
      startRate: 5,
      timeUnit: '1s',
      preAllocatedVUs: Number(__ENV.LIVE_LOG_VUS || 30),
      maxVUs: Number(__ENV.LIVE_LOG_MAX_VUS || 220),
      stages: [
        { duration: '30s', target: 15 },
        { duration: '45s', target: 25 },
        { duration: '45s', target: 35 },
        { duration: '45s', target: 45 },
        { duration: '15s', target: 0 },
      ],
      tags: { hotspot: 'live_log' },
    },
  },
};

export function liveLogHotspot() {
  const res = http.get(`${BASE_URL}/api/packets/live?limit=50`, {
    timeout: TIMEOUT,
    tags: { app: 'malla', profile: 'live-log-focus', endpoint: 'api_live_packets' },
  });

  liveLogLatency.add(res.timings.duration);
  liveLogErrors.add(res.status !== 200);

  check(res, {
    'status is 200': (response) => response.status === 200,
  });
}
