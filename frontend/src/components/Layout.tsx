import {
  Activity,
  Bell,
  BookOpenCheck,
  CircleHelp,
  Database,
  FileSearch,
  FileInput,
  Gauge,
  Home,
  ListChecks,
  Monitor,
  Moon,
  Network,
  PlaySquare,
  RadioTower,
  Settings2,
  Sun
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { RoleGuide } from "./RoleGuide";
import { useRole, type UserRole } from "../context/RoleContext";
import { useTheme, type ThemePreference } from "../context/ThemeContext";

const navItems = [
  { to: "/dashboard", label: "Dashboard", icon: Home, roles: ["executive", "operator", "dba"] },
  { to: "/runs", label: "Runs", icon: Activity, roles: ["executive", "operator", "dba"] },
  { to: "/expectations", label: "Expectations", icon: Gauge, roles: ["operator"] },
  { to: "/alerts", label: "Alerts", icon: Bell, roles: ["executive", "operator"] },
  { to: "/diagnostics", label: "Diagnostics", icon: FileSearch, roles: ["executive", "operator", "dba"] },
  { to: "/topology", label: "Topology", icon: Network, roles: ["executive", "operator", "dba"] },
  { to: "/ad-hoc", label: "Ad Hoc", icon: RadioTower, roles: ["operator"] },
  { to: "/sources", label: "Sources", icon: Database, roles: ["operator", "dba"] },
  { to: "/query-templates", label: "Queries", icon: Settings2, roles: ["operator", "dba"] },
  { to: "/imports", label: "Imports", icon: FileInput, roles: ["operator"] },
  { to: "/playbook", label: "Playbook", icon: BookOpenCheck, roles: ["executive", "operator", "dba"] },
  { to: "/help", label: "Help", icon: CircleHelp, roles: ["executive", "operator", "dba"] }
];

export function Layout({ children }: { children: ReactNode }) {
  const { role, setRole, config, roles, customerPod, setCustomerPod, customerPods } = useRole();
  const { themePreference, setThemePreference, resolvedTheme } = useTheme();
  const selectedPod = customerPods.find((pod) => pod.key === customerPod) ?? customerPods[0];
  const ThemeIcon = themePreference === "system" ? Monitor : themePreference === "dark" ? Moon : Sun;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <PlaySquare aria-hidden />
          <div>
            <strong>JobRun Sentinel</strong>
            <span>Oracle job runtime watch</span>
          </div>
        </div>
        <div className="pod-selector">
          <label>
            Customer pod
            <select value={customerPod} onChange={(event) => setCustomerPod(event.target.value)}>
              {customerPods.map((pod) => (
                <option key={pod.key} value={pod.key}>
                  {pod.label}
                </option>
              ))}
            </select>
          </label>
          <small>{selectedPod.description}</small>
        </div>
        <nav>
          {navItems.filter((item) => item.roles.includes(role)).map((item) => {
            const Icon = item.icon;
            return (
              <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
                <Icon size={18} aria-hidden />
                {item.label}
              </NavLink>
            );
          })}
        </nav>
      </aside>
      <main className="main-pane">
        <header className="topbar">
          <div>
            <span className="eyebrow">Runtime operations</span>
            <h1>Slow-job detection and explanation</h1>
          </div>
          <div className="topbar-controls">
            <div className="theme-control">
              <label>
                <ThemeIcon size={16} aria-hidden />
                <span>Theme</span>
                <select
                  value={themePreference}
                  onChange={(event) => setThemePreference(event.target.value as ThemePreference)}
                >
                  <option value="system">System</option>
                  <option value="light">Light</option>
                  <option value="dark">Dark</option>
                </select>
              </label>
              <small>{resolvedTheme === "dark" ? "Dark interface" : "Light interface"}</small>
            </div>
            <div className="role-control">
            <label>
              <ListChecks size={16} aria-hidden />
              <span>View</span>
              <select value={role} onChange={(event) => setRole(event.target.value as UserRole)}>
                {roles.map((item) => (
                  <option key={item.role} value={item.role}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <small>{config.shortLabel}: {config.primaryQuestion}</small>
            </div>
          </div>
        </header>
        <RoleGuide />
        {children}
      </main>
    </div>
  );
}
