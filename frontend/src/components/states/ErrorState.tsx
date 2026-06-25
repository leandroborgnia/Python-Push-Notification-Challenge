import { Button, Result } from "antd";

/** Shared error state with a retry affordance (FR-035 / ui-routes states table). */
export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <Result
      status="warning"
      title="Something went wrong"
      subTitle={message ?? "Please try again."}
      extra={
        onRetry ? (
          <Button type="primary" onClick={onRetry}>
            Retry
          </Button>
        ) : undefined
      }
    />
  );
}
