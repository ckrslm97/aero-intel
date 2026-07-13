import { useSyncExternalStore } from "react";

const emptySubscribe = () => () => {};

/** True only after client hydration -- avoids the setState-in-effect anti-pattern for SSR/client guards. */
export function useMounted(): boolean {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );
}
