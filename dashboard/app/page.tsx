import { Suspense } from "react";
import { OverviewView } from "@/components/OverviewView";
import { Loading } from "@/components/Status";

export default function Page() {
  return <Suspense fallback={<Loading />}><OverviewView /></Suspense>;
}
