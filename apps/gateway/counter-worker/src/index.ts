export { CounterObject } from "./counter-object";

export default {
  fetch: () => new Response(null, { status: 404 }),
} satisfies ExportedHandler;
