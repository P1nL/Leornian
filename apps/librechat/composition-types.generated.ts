export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * BfsScene
         * @description One shared timeline; adjacency follows the supplied edge order.
         */
        BfsScene: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "bfs";
            /** Nodes */
            nodes: string[];
            /** Edges */
            edges: components["schemas"]["DirectedEdge"][];
            /** Start */
            start: string;
            /**
             * Views
             * @description Unique views; graph is required. All views share one playback step.
             */
            views: ("graph" | "queue" | "code" | "variables")[];
        };
        /** CodeRepairScene */
        CodeRepairScene: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "code_repair";
            /** Prompt */
            prompt: string;
            /** Code */
            code: string;
            /** Cases */
            cases: components["schemas"]["PublicCase"][];
            /**
             * Views
             * @description Unique views; editor is required. Diff compares the draft with original code.
             */
            views: ("editor" | "diff" | "cases")[];
        };
        /** CodeReviewScene */
        CodeReviewScene: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "code_review";
            /** Prompt */
            prompt: string;
            /** Code */
            code: string;
        };
        /** DirectedEdge */
        DirectedEdge: {
            /** Source */
            source: string;
            /** Target */
            target: string;
        };
        /** PublicCase */
        PublicCase: {
            /** Input */
            input: string;
            /** Expected */
            expected: string;
        };
        /**
         * LearningComposition
         * @description The host separately binds this proposal to an authorized artifact/revision.
         */
        LearningComposition: {
            /**
             * Schema Version
             * @constant
             */
            schema_version: "learning_composition.v1";
            /** Title */
            title: string;
            /** Scene */
            scene: components["schemas"]["BfsScene"] | components["schemas"]["CodeReviewScene"] | components["schemas"]["CodeRepairScene"];
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export type operations = Record<string, never>;
