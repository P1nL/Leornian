export type paths = Record<string, never>;
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** ActionGroupComponent */
        ActionGroupComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "ActionGroup";
            props: components["schemas"]["GroupProps"];
        };
        /** ActionProps */
        ActionProps: {
            /** Label */
            label: string;
            /**
             * Event
             * @enum {string}
             */
            event: "submit_answer" | "submit_review" | "check_code" | "preview" | "cancel";
            /** For Component */
            for_component: string;
            /**
             * Primary
             * @default false
             */
            primary: boolean;
        };
        /** AlgorithmBitsComponent */
        AlgorithmBitsComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AlgorithmBits";
            props: components["schemas"]["AlgorithmViewProps"];
        };
        /** AlgorithmContainerComponent */
        AlgorithmContainerComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AlgorithmContainer";
            props: components["schemas"]["AlgorithmViewProps"];
        };
        /** AlgorithmGeometryComponent */
        AlgorithmGeometryComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AlgorithmGeometry";
            props: components["schemas"]["AlgorithmViewProps"];
        };
        /** AlgorithmGraphComponent */
        AlgorithmGraphComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AlgorithmGraph";
            props: components["schemas"]["AlgorithmViewProps"];
        };
        /** AlgorithmGridComponent */
        AlgorithmGridComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AlgorithmGrid";
            props: components["schemas"]["AlgorithmViewProps"];
        };
        /** AlgorithmIntervalsComponent */
        AlgorithmIntervalsComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AlgorithmIntervals";
            props: components["schemas"]["AlgorithmViewProps"];
        };
        /** AlgorithmPlayerComponent */
        AlgorithmPlayerComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AlgorithmPlayer";
            props: components["schemas"]["AlgorithmProps"];
        };
        /**
         * AlgorithmProps
         * @description Algorithm inputs, never model-generated frames or executable algorithms.
         */
        AlgorithmProps: {
            /** Label */
            label: string;
            /**
             * Algorithm
             * @enum {string}
             */
            algorithm: "binary_search" | "brackets" | "bfs" | "grid_paths" | "combination_sum" | "interval_scan" | "bitwise" | "geometry";
            /** State */
            state: string;
            /** Input */
            input: string;
            /**
             * Show Code
             * @default true
             */
            show_code: boolean;
            /**
             * Show Variables
             * @default true
             */
            show_variables: boolean;
        };
        /** AlgorithmRecursionComponent */
        AlgorithmRecursionComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AlgorithmRecursion";
            props: components["schemas"]["AlgorithmViewProps"];
        };
        /** AlgorithmSequenceComponent */
        AlgorithmSequenceComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AlgorithmSequence";
            props: components["schemas"]["AlgorithmViewProps"];
        };
        /** AlgorithmViewProps */
        AlgorithmViewProps: {
            /** Label */
            label: string;
            /** Timeline */
            timeline: string;
        };
        /** AnnotationProps */
        AnnotationProps: {
            /** Label */
            label: string;
            /** Code State */
            code_state: string;
            /** State */
            state: string;
        };
        /** AnnotationState */
        AnnotationState: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "annotations";
            /** Value */
            value?: string[];
        };
        /** AnswerFeedbackComponent */
        AnswerFeedbackComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "AnswerFeedback";
            props: components["schemas"]["FeedbackProps"];
        };
        /** ArtifactActionComponent */
        ArtifactActionComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "ArtifactAction";
            props: components["schemas"]["ActionProps"];
        };
        /** BfsInput */
        BfsInput: {
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
        };
        /** BinarySearchInput */
        BinarySearchInput: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "binary_search";
            /** Values */
            values: number[];
            /** Target State */
            target_state: string;
        };
        /** BitsInput */
        BitsInput: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "bitwise";
            /** Left */
            left: number;
            /** Right */
            right: number;
            /**
             * Operation
             * @enum {string}
             */
            operation: "and" | "or" | "xor";
            /** Width */
            width: number;
        };
        /** BracketsInput */
        BracketsInput: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "brackets";
            /** Text */
            text: string;
        };
        /** ChoiceAnswerComponent */
        ChoiceAnswerComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "ChoiceAnswer";
            props: components["schemas"]["ChoiceProps"];
        };
        /** ChoiceProps */
        ChoiceProps: {
            /** Label */
            label: string;
            /** Options */
            options: components["schemas"]["Option"][];
            /**
             * Multiple
             * @default false
             */
            multiple: boolean;
            /** State */
            state: string;
        };
        /** ChoiceState */
        ChoiceState: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "choice";
            /** Value */
            value?: string[];
        };
        /** CitationProps */
        CitationProps: {
            /** Label */
            label: string;
            /** Citation */
            citation: components["schemas"]["MaterialCitation"] | components["schemas"]["SourceRef"];
        };
        /** CodeBlockComponent */
        CodeBlockComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "CodeBlock";
            props: components["schemas"]["CodeProps"];
        };
        /** CodeDiffComponent */
        CodeDiffComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "CodeDiff";
            props: components["schemas"]["DiffProps"];
        };
        /** CodeEditorComponent */
        CodeEditorComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "CodeEditor";
            props: components["schemas"]["CodeProps"];
        };
        /** CodeProps */
        CodeProps: {
            /** Label */
            label: string;
            /** State */
            state: string;
        };
        /** CodeState */
        CodeState: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "code";
            /** Value */
            value: string;
            /**
             * Read Only
             * @default false
             */
            read_only: boolean;
        };
        /**
         * CombinationInput
         * @description Positive subset sum: each input position is considered at most once.
         */
        CombinationInput: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "combination_sum";
            /** Values */
            values: number[];
            /** Target */
            target: number;
        };
        /** DataTableComponent */
        DataTableComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "DataTable";
            props: components["schemas"]["TableProps"];
        };
        /** DiffProps */
        DiffProps: {
            /** Label */
            label: string;
            /** State */
            state: string;
            /** Before */
            before: string;
        };
        /** DirectedEdge */
        DirectedEdge: {
            /** Source */
            source: string;
            /** Target */
            target: string;
        };
        /** ExplanationComponent */
        ExplanationComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "Explanation";
            props: components["schemas"]["TextProps"];
        };
        /** FeedbackProps */
        FeedbackProps: {
            /** Label */
            label: string;
            /** For Component */
            for_component: string;
        };
        /** FilesState */
        FilesState: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "files";
            /** Files */
            files: components["schemas"]["ProjectFile"][];
        };
        /**
         * GeometryInput
         * @description Orientation of three points by the signed cross product.
         */
        GeometryInput: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "geometry";
            /** Points */
            points: components["schemas"]["Point"][];
        };
        /** GraphEdge */
        GraphEdge: {
            /** Source */
            source: string;
            /** Target */
            target: string;
            /**
             * Label
             * @default null
             */
            label: string | null;
        };
        /** GraphNode */
        GraphNode: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** X */
            x: number;
            /** Y */
            y: number;
        };
        /** GraphProps */
        GraphProps: {
            /** Label */
            label: string;
            /** Nodes */
            nodes: components["schemas"]["GraphNode"][];
            /** Edges */
            edges: components["schemas"]["GraphEdge"][];
            /** State */
            state: string;
        };
        /** GridCell */
        GridCell: {
            /** Row */
            row: number;
            /** Column */
            column: number;
        };
        /** GridPathsInput */
        GridPathsInput: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "grid_paths";
            /** Rows */
            rows: number;
            /** Columns */
            columns: number;
            /** Blocked */
            blocked?: components["schemas"]["GridCell"][];
        };
        /** GroupProps */
        GroupProps: {
            /** Members */
            members: string[];
        };
        /** Interval */
        Interval: {
            /** Id */
            id: string;
            /** Start */
            start: number;
            /** End */
            end: number;
        };
        /** IntervalsInput */
        IntervalsInput: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "interval_scan";
            /** Intervals */
            intervals: components["schemas"]["Interval"][];
        };
        /** IsolatedPreviewComponent */
        IsolatedPreviewComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "IsolatedPreview";
            props: components["schemas"]["PreviewProps"];
        };
        /** KeyValueListComponent */
        KeyValueListComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "KeyValueList";
            props: components["schemas"]["ValuesProps"];
        };
        /** LineRangeAnswerComponent */
        LineRangeAnswerComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "LineRangeAnswer";
            props: components["schemas"]["AnnotationProps"];
        };
        /** MaterialCitation */
        MaterialCitation: {
            /**
             * Binding Id
             * Format: uuid
             */
            binding_id: string;
            /** Binding Revision */
            binding_revision: number;
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "reference" | "planning" | "lesson" | "teaching" | "item_author" | "item_review" | "indexing";
            ref: components["schemas"]["MaterialRef"];
        };
        /** MaterialRef */
        MaterialRef: {
            /**
             * Document Id
             * Format: uuid
             */
            document_id: string;
            /** Document Revision */
            document_revision: number;
            /**
             * Block Id
             * Format: uuid
             */
            block_id: string;
            span: components["schemas"]["MaterialSpan"];
            /** Content Digest */
            content_digest: string;
            /**
             * Selection Id
             * @default null
             */
            selection_id: string | null;
        };
        /** MaterialSpan */
        MaterialSpan: {
            /** Start */
            start: number;
            /** End */
            end: number;
        };
        /** NamedValue */
        NamedValue: {
            /** Name */
            name: string;
            /** Value */
            value: string;
        };
        /** NumberState */
        NumberState: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "number";
            /** Value */
            value: number;
        };
        /** Option */
        Option: {
            /** Id */
            id: string;
            /** Text */
            text: string;
        };
        /** OrderState */
        OrderState: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "order";
            /** Value */
            value: string[];
        };
        /** OrderingAnswerComponent */
        OrderingAnswerComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "OrderingAnswer";
            props: components["schemas"]["OrderingProps"];
        };
        /** OrderingProps */
        OrderingProps: {
            /** Label */
            label: string;
            /** Items */
            items: components["schemas"]["Option"][];
            /** State */
            state: string;
        };
        /** ParameterControlComponent */
        ParameterControlComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "ParameterControl";
            props: components["schemas"]["ParameterProps"];
        };
        /** ParameterProps */
        ParameterProps: {
            /** Label */
            label: string;
            /** State */
            state: string;
            /** Minimum */
            minimum: number;
            /** Maximum */
            maximum: number;
            /**
             * Step
             * @default 1
             */
            step: number;
        };
        /** Participant */
        Participant: {
            /** Id */
            id: string;
            /** Label */
            label: string;
        };
        /** PlaybackState */
        PlaybackState: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "playback";
            /**
             * Value
             * @default 0
             * @constant
             */
            value: 0;
        };
        /** Point */
        Point: {
            /** Id */
            id: string;
            /** X */
            x: number;
            /** Y */
            y: number;
        };
        /** PreviewProps */
        PreviewProps: {
            /** Title */
            title: string;
            /** Html State */
            html_state: string;
            /**
             * Css State
             * @default null
             */
            css_state: string | null;
        };
        /** ProjectFile */
        ProjectFile: {
            /** Path */
            path: string;
            /** Content */
            content: string;
            /**
             * Read Only
             * @default false
             */
            read_only: boolean;
        };
        /** RelationGraphComponent */
        RelationGraphComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "RelationGraph";
            props: components["schemas"]["GraphProps"];
        };
        /** ResultFeedbackComponent */
        ResultFeedbackComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "ResultFeedback";
            props: components["schemas"]["FeedbackProps"];
        };
        /** ReviewFindingComponent */
        ReviewFindingComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "ReviewFinding";
            props: components["schemas"]["FeedbackProps"];
        };
        /** SelectionState */
        SelectionState: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "selection";
            /**
             * Value
             * @default null
             */
            value: string | null;
        };
        /** SequenceDiagramComponent */
        SequenceDiagramComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "SequenceDiagram";
            props: components["schemas"]["SequenceProps"];
        };
        /** SequenceProps */
        SequenceProps: {
            /** Label */
            label: string;
            /** Participants */
            participants: components["schemas"]["Participant"][];
            /** Steps */
            steps: components["schemas"]["SequenceStep"][];
            /** State */
            state: string;
        };
        /** SequenceStep */
        SequenceStep: {
            /** Source */
            source: string;
            /** Target */
            target: string;
            /** Label */
            label: string;
            /** Id */
            id: string;
        };
        /** SourceRef */
        SourceRef: {
            /**
             * Source Id
             * Format: uuid
             */
            source_id: string;
            /** Revision */
            revision: number;
        };
        /** SourceReferenceComponent */
        SourceReferenceComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "SourceReference";
            props: components["schemas"]["CitationProps"];
        };
        /** StepPlayerComponent */
        StepPlayerComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "StepPlayer";
            props: components["schemas"]["StepsProps"];
        };
        /** StepsProps */
        StepsProps: {
            /** Label */
            label: string;
            /** Items */
            items: string[];
            /** State */
            state: string;
        };
        /** TableProps */
        TableProps: {
            /** Label */
            label: string;
            /** Columns */
            columns: string[];
            /** Rows */
            rows: string[][];
        };
        /** TextAnswerComponent */
        TextAnswerComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "TextAnswer";
            props: components["schemas"]["TextAnswerProps"];
        };
        /** TextAnswerProps */
        TextAnswerProps: {
            /** Label */
            label: string;
            /** State */
            state: string;
        };
        /** TextProps */
        TextProps: {
            /**
             * Title
             * @default null
             */
            title: string | null;
            /** Text */
            text: string;
        };
        /** TextState */
        TextState: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "text";
            /**
             * Value
             * @default
             * @constant
             */
            value: "";
        };
        /** TreeEntry */
        TreeEntry: {
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Children */
            children?: components["schemas"]["TreeEntry"][];
        };
        /** TreeProps */
        TreeProps: {
            /** Label */
            label: string;
            /** Nodes */
            nodes: components["schemas"]["TreeEntry"][];
            /** State */
            state: string;
        };
        /** TreeViewComponent */
        TreeViewComponent: {
            /** Id */
            id: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            component: "TreeView";
            props: components["schemas"]["TreeProps"];
        };
        /** ValuesProps */
        ValuesProps: {
            /** Label */
            label: string;
            /** Entries */
            entries: components["schemas"]["NamedValue"][];
        };
        /** LearningCompositionV2 */
        LearningCompositionV2: {
            /**
             * Schema Version
             * @constant
             */
            schema_version: "learning_composition.v2";
            /** Title */
            title: string;
            /**
             * Layout
             * @default stack
             * @enum {string}
             */
            layout: "stack" | "split";
            /** States */
            states?: {
                [key: string]: components["schemas"]["CodeState"] | components["schemas"]["TextState"] | components["schemas"]["ChoiceState"] | components["schemas"]["OrderState"] | components["schemas"]["AnnotationState"] | components["schemas"]["PlaybackState"] | components["schemas"]["NumberState"] | components["schemas"]["SelectionState"] | components["schemas"]["FilesState"];
            };
            /** Inputs */
            inputs?: {
                [key: string]: components["schemas"]["BinarySearchInput"] | components["schemas"]["BracketsInput"] | components["schemas"]["BfsInput"] | components["schemas"]["GridPathsInput"] | components["schemas"]["CombinationInput"] | components["schemas"]["IntervalsInput"] | components["schemas"]["BitsInput"] | components["schemas"]["GeometryInput"];
            };
            /** Components */
            components: (components["schemas"]["ExplanationComponent"] | components["schemas"]["SourceReferenceComponent"] | components["schemas"]["CodeBlockComponent"] | components["schemas"]["CodeEditorComponent"] | components["schemas"]["CodeDiffComponent"] | components["schemas"]["DataTableComponent"] | components["schemas"]["KeyValueListComponent"] | components["schemas"]["IsolatedPreviewComponent"] | components["schemas"]["TreeViewComponent"] | components["schemas"]["RelationGraphComponent"] | components["schemas"]["SequenceDiagramComponent"] | components["schemas"]["AlgorithmPlayerComponent"] | components["schemas"]["AlgorithmSequenceComponent"] | components["schemas"]["AlgorithmContainerComponent"] | components["schemas"]["AlgorithmGraphComponent"] | components["schemas"]["AlgorithmGridComponent"] | components["schemas"]["AlgorithmRecursionComponent"] | components["schemas"]["AlgorithmIntervalsComponent"] | components["schemas"]["AlgorithmBitsComponent"] | components["schemas"]["AlgorithmGeometryComponent"] | components["schemas"]["ChoiceAnswerComponent"] | components["schemas"]["TextAnswerComponent"] | components["schemas"]["OrderingAnswerComponent"] | components["schemas"]["LineRangeAnswerComponent"] | components["schemas"]["ParameterControlComponent"] | components["schemas"]["StepPlayerComponent"] | components["schemas"]["AnswerFeedbackComponent"] | components["schemas"]["ResultFeedbackComponent"] | components["schemas"]["ReviewFindingComponent"] | components["schemas"]["ArtifactActionComponent"] | components["schemas"]["ActionGroupComponent"])[];
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
