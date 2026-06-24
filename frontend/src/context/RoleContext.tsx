import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";

export type UserRole = "executive" | "operator" | "dba";

export interface RoleConfig {
  role: UserRole;
  label: string;
  shortLabel: string;
  headline: string;
  help: string;
  primaryQuestion: string;
}

export interface CustomerPod {
  key: string;
  label: string;
  description: string;
}

const ROLE_CONFIG: Record<UserRole, RoleConfig> = {
  executive: {
    role: "executive",
    label: "Executive",
    shortLabel: "Exec",
    headline: "Executive status pane",
    help: "Shows customer impact, active critical risk, top business-process exposure, and concise recommended focus without database-level detail.",
    primaryQuestion: "What is at risk, where is it concentrated, and what needs executive attention?"
  },
  operator: {
    role: "operator",
    label: "Operator",
    shortLabel: "Ops",
    headline: "Support operations",
    help: "Shows runtime state, reason codes, alerts, recommended actions, and enough context to triage or acknowledge alerts.",
    primaryQuestion: "What needs action, who owns it, and what should be checked next?"
  },
  dba: {
    role: "dba",
    label: "DBA",
    shortLabel: "DBA",
    headline: "Database investigation",
    help: "Emphasizes SQL_ID, plan hash, UDQ hash, waits, volume shape, and direct read-only query diagnostics.",
    primaryQuestion: "Did SQL, plan, volume, or customer-authored query shape change?"
  }
};

interface RoleContextValue {
  role: UserRole;
  setRole: (role: UserRole) => void;
  config: RoleConfig;
  roles: RoleConfig[];
  customerPod: string;
  setCustomerPod: (customerKey: string) => void;
  customerPods: CustomerPod[];
}

const RoleContext = createContext<RoleContextValue | null>(null);

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<UserRole>(() => {
    const stored = window.localStorage.getItem("jobrun-sentinel-role");
    return stored === "executive" || stored === "operator" || stored === "dba" ? stored : "operator";
  });
  const [customerPod, setCustomerPodState] = useState<string>(() => {
    return window.localStorage.getItem("jobrun-sentinel-customer-pod") ?? "all";
  });
  const [remotePods, setRemotePods] = useState<CustomerPod[]>([]);

  useEffect(() => {
    let cancelled = false;
    api.customerPods()
      .then((pods) => {
        if (cancelled || !Array.isArray(pods)) return;
        setRemotePods(
          pods
            .filter((pod) => typeof pod.customer_key === "string" && typeof pod.display_name === "string")
            .map((pod) => ({
              key: pod.customer_key,
              label: pod.display_name,
              description: `${pod.tier ?? "production"} customer pod from Sentinel backend.`
            }))
        );
      })
      .catch(() => {
        if (!cancelled) setRemotePods([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const customerPods = useMemo(() => mergeCustomerPods(CUSTOMER_PODS, remotePods, customerPod), [customerPod, remotePods]);

  const value = useMemo<RoleContextValue>(() => {
    return {
      role,
      setRole: (nextRole: UserRole) => {
        window.localStorage.setItem("jobrun-sentinel-role", nextRole);
        setRole(nextRole);
      },
      config: ROLE_CONFIG[role],
      roles: Object.values(ROLE_CONFIG),
      customerPod,
      setCustomerPod: (customerKey: string) => {
        window.localStorage.setItem("jobrun-sentinel-customer-pod", customerKey);
        setCustomerPodState(customerKey);
      },
      customerPods
    };
  }, [customerPod, customerPods, role]);

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function customerPodParam(customerPod: string): Record<string, string> {
  return customerPod === "all" ? {} : { customer_key: customerPod };
}

const CUSTOMER_PODS: CustomerPod[] = [
  { key: "all", label: "All customer pods", description: "Show every customer in the dataset." },
  { key: "CUST_A", label: "Customer A", description: "Original APJ/EMEA/AMER-LATAM scenario." },
  { key: "CUST_B", label: "Customer B", description: "Run Revert and learning-mode scenario." },
  ...Array.from({ length: 10 }, (_, index) => {
    const number = index + 1;
    return {
      key: `DEMO_CUST_${String(number).padStart(2, "0")}`,
      label: `Demo Customer ${number}`,
      description: `Scale-test customer pod ${number}.`
    };
  })
];

function mergeCustomerPods(staticPods: CustomerPod[], remotePods: CustomerPod[], selectedKey: string): CustomerPod[] {
  const byKey = new Map<string, CustomerPod>();
  for (const pod of staticPods) byKey.set(pod.key, pod);
  for (const pod of remotePods) byKey.set(pod.key, pod);
  if (selectedKey !== "all" && !byKey.has(selectedKey)) {
    byKey.set(selectedKey, {
      key: selectedKey,
      label: selectedKey,
      description: "Selected customer pod. Details will load after backend registration."
    });
  }
  return Array.from(byKey.values());
}

export function useRole() {
  const context = useContext(RoleContext);
  if (!context) {
    throw new Error("useRole must be used inside RoleProvider");
  }
  return context;
}
