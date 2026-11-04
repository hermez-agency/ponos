// openapi-typescript builds the declarations of `npm run types` with the
// compiler API of the `typescript` package, which TypeScript 7 no longer ships:
// its `typescript` is the native `tsc` and a version number. A peer dependency
// cannot be nested, so npm hands openapi-typescript the TypeScript 7 of the
// console (the `$typescript` override says so, for `npm ci`), and the
// TypeScript 5.9 it was written for sits beside it as `typescript-5`. This hook
// gives it that one instead, for the `npm run types` command (`node --import`)
// and for openapi-typescript only: `tsc -b` and everything else keep
// TypeScript 7.
//
// `typescript-5` rather than `@typescript/typescript6`: both packages declare a
// `tsc`, and npm links the binary of the first path in order —
// `node_modules/@typescript/old`, the TypeScript 6 that the latter pulls in,
// would win over `node_modules/typescript`; `node_modules/typescript-5` does not.
import { registerHooks } from "node:module";

registerHooks({
  resolve(specifier, context, next) {
    const fromOpenapi = context.parentURL?.includes("/node_modules/openapi-typescript/");
    return next(fromOpenapi && specifier === "typescript" ? "typescript-5" : specifier, context);
  },
});
