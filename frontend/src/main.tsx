import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppErrorBoundary } from "./components/AppErrorBoundary";
import { Layout } from "./components/Layout";
import { RoleProvider } from "./context/RoleContext";
import { ThemeProvider } from "./context/ThemeContext";
import "./styles.css";

const DashboardPage = lazy(() => import("./pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const RunsPage = lazy(() => import("./pages/RunsPage").then((module) => ({ default: module.RunsPage })));
const RunDetailPage = lazy(() => import("./pages/RunDetailPage").then((module) => ({ default: module.RunDetailPage })));
const ExpectationsPage = lazy(() => import("./pages/ExpectationsPage").then((module) => ({ default: module.ExpectationsPage })));
const AlertsPage = lazy(() => import("./pages/AlertsPage").then((module) => ({ default: module.AlertsPage })));
const AdHocPage = lazy(() => import("./pages/AdHocPage").then((module) => ({ default: module.AdHocPage })));
const SourcesPage = lazy(() => import("./pages/SourcesPage").then((module) => ({ default: module.SourcesPage })));
const QueryTemplatesPage = lazy(() => import("./pages/QueryTemplatesPage").then((module) => ({ default: module.QueryTemplatesPage })));
const DiagnosticsPage = lazy(() => import("./pages/DiagnosticsPage").then((module) => ({ default: module.DiagnosticsPage })));
const DiagnosticDetailPage = lazy(() => import("./pages/DiagnosticDetailPage").then((module) => ({ default: module.DiagnosticDetailPage })));
const TopologyPage = lazy(() => import("./pages/TopologyPage").then((module) => ({ default: module.TopologyPage })));
const ImportsPage = lazy(() => import("./pages/ImportsPage").then((module) => ({ default: module.ImportsPage })));
const PlaybookPage = lazy(() => import("./pages/PlaybookPage").then((module) => ({ default: module.PlaybookPage })));
const HelpPage = lazy(() => import("./pages/HelpPage").then((module) => ({ default: module.HelpPage })));

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <RoleProvider>
        <BrowserRouter>
          <Layout>
            <AppErrorBoundary>
              <Suspense fallback={<div className="state-panel">Loading view...</div>}>
                <Routes>
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/dashboard" element={<DashboardPage />} />
                  <Route path="/runs" element={<RunsPage />} />
                  <Route path="/runs/:id" element={<RunDetailPage />} />
                  <Route path="/expectations" element={<ExpectationsPage />} />
                  <Route path="/alerts" element={<AlertsPage />} />
                  <Route path="/ad-hoc" element={<AdHocPage />} />
                  <Route path="/sources" element={<SourcesPage />} />
                  <Route path="/query-templates" element={<QueryTemplatesPage />} />
                  <Route path="/diagnostics" element={<DiagnosticsPage />} />
                  <Route path="/diagnostics/:id" element={<DiagnosticDetailPage />} />
                  <Route path="/topology" element={<TopologyPage />} />
                  <Route path="/imports" element={<ImportsPage />} />
                  <Route path="/playbook" element={<PlaybookPage />} />
                  <Route path="/help" element={<HelpPage />} />
                </Routes>
              </Suspense>
            </AppErrorBoundary>
          </Layout>
        </BrowserRouter>
      </RoleProvider>
    </ThemeProvider>
  </React.StrictMode>
);
