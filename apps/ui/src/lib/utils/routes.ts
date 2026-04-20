export const APP_ROUTES = {
  dashboard: "/",
  files: "/files",
  fileDetail: (fileId: string) => `/files/${fileId}`,
  jobs: "/jobs",
  jobDetail: (jobId: string) => `/jobs/${jobId}`,
  system: "/system",
  config: "/config",
  login: "/login",
} as const;
