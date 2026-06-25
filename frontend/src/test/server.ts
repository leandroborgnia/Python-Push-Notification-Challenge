import { setupServer } from "msw/node";

import { handlers } from "./handlers";

// One MSW server shared across the suite; wired into the Vitest lifecycle in src/setupTests.ts.
export const server = setupServer(...handlers);
