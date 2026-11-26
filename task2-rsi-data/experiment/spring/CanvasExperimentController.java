package com.horsecoder.common.whuTalent.core.flow;

import cc.eamon.open.flow.config.constants.FlowConstants;
import cc.eamon.open.flow.config.flow.FlowConfig;
import cc.eamon.open.flow.config.flow.FlowNodeConfig;
import cc.eamon.open.flow.core.FlowEngine;
import cc.eamon.open.flow.core.context.Initializer;
import cc.eamon.open.flow.core.context.InitializerEnums;
import cc.eamon.open.flow.core.stereotype.execute.holder.FlowHolder;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.Collections;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

/** Compile validated canvas nodes into RSI Flow events and execute them in dependency order. */
@RestController
@RequestMapping("/api/task2-experiment")
public class CanvasExperimentController {
    static final String WORKER = "http://127.0.0.1:3213";
    static final String NODE = "TASK2_CANVAS_EXPERIMENT_STEP";
    private static final Logger log = LoggerFactory.getLogger(CanvasExperimentController.class);
    private final ObjectMapper mapper = new ObjectMapper();
    private final RestTemplate worker = worker();
    private final Set<String> registered = new HashSet<>();

    static RestTemplate worker() {
        SimpleClientHttpRequestFactory timeouts = new SimpleClientHttpRequestFactory();
        timeouts.setConnectTimeout(3000);
        timeouts.setReadTimeout(220000);
        return new RestTemplate(timeouts);
    }

    @PostMapping("/run")
    public JsonNode run(@RequestBody ObjectNode request) throws Exception {
        JsonNode initialized = worker.postForObject(WORKER + "/begin", request, JsonNode.class);
        String runId = initialized.path("run_id").asText();
        String flowId = "TASK2_CANVAS_" + initialized.path("graph_sha256").asText();
        ObjectNode flow = compile(flowId, initialized.path("sequence"));
        register(flowId, flow);

        FlowEngine engine = FlowEngine.instance();
        try {
            engine.registerWithDefaultScope("canvasRunId", runId);
            engine.run(flowId);
        } catch (Exception error) {
            log.error("Canvas flow execution failed for {}", flowId, error);
            throw error;
        } finally {
            engine.release();
        }
        ObjectNode body = mapper.createObjectNode().put("run_id", runId);
        ObjectNode result = worker.postForObject(WORKER + "/finish", body, ObjectNode.class);
        result.put("course_flow_id", flowId);
        result.set("course_flow", flow);
        return result;
    }

    private synchronized void register(String id, ObjectNode flow) throws Exception {
        if (registered.contains(id)) {
            return;
        }
        if (registered.size() == 128) {
            throw new IllegalStateException("Too many local canvas variants. Restart the course service.");
        }
        Initializer registry = InitializerEnums.DEFAULT.getInitializer();
        FlowConfig config = mapper.treeToValue(flow, FlowConfig.class);
        FlowHolder holder = new FlowHolder(config);
        Map<FlowNodeConfig, FlowConfig> owners = new IdentityHashMap<>();
        for (FlowNodeConfig node : config.getNodes()) {
            owners.put(node, config);
        }
        registry.addFlowNodeConfigFlowConfig(owners);
        registry.addExtraFlowConfig(Collections.singletonMap(id, config));
        registry.addExtraFlowHolder(Collections.singletonMap(id, holder));
        registered.add(id);
    }

    private ObjectNode compile(String id, JsonNode sequence) {
        ObjectNode flow = mapper.createObjectNode().put("id", id).put("type", "flow")
                .put("name", "Task 2 canvas experiment");
        addParameter(flow);
        flow.putArray("results");
        ArrayNode nodes = flow.putArray("nodes");
        ArrayNode routes = flow.putArray("routes");
        String previous = "start";
        for (JsonNode item : sequence) {
            String next = "canvas_" + item.asText();
            ObjectNode node = nodes.addObject().put("id", next).put("type", "event")
                    .put("title", item.asText()).put("reference", NODE);
            addParameter(node);
            node.putArray("results");
            routes.addObject().put("source", previous).put("target", next);
            previous = next;
        }
        routes.addObject().put("source", previous).put("target", "end");
        return flow;
    }

    private void addParameter(ObjectNode node) {
        node.putArray("params").addObject().put("name", "canvasRunId").put("type", "String")
                .put("scope", FlowConstants.SCOPE_DEFAULT);
    }
}
