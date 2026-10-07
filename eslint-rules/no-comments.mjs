const DISABLE_NEXT_LINE = /^ eslint-disable-next-line [@a-z0-9/-]+(, [@a-z0-9/-]+)*$/;
const EXPECT_ERROR = /^ @ts-expect-error$/;

export default {
  meta: {
    type: "problem",
    schema: [
      {
        type: "object",
        properties: { allowTsExpectError: { type: "boolean" } },
        additionalProperties: false,
      },
    ],
    messages: { comment: "Comments are not allowed" },
  },
  create(context) {
    const allowExpectError = context.options[0]?.allowTsExpectError === true;
    const isAllowed = (comment) =>
      comment.type === "Line" &&
      (DISABLE_NEXT_LINE.test(comment.value) ||
        (allowExpectError && EXPECT_ERROR.test(comment.value)));
    return {
      Program() {
        for (const comment of context.sourceCode.getAllComments()) {
          if (!isAllowed(comment)) {
            context.report({ loc: comment.loc, messageId: "comment" });
          }
        }
      },
    };
  },
};
