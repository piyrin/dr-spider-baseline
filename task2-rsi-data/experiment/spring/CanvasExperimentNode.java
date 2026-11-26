package com.horsecoder.common.whuTalent.core.flow;

import cc.eamon.open.flow.core.stereotype.Flow;
import cc.eamon.open.flow.spring.FlowComponent;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.web.client.RestTemplate;

@FlowComponent
public class CanvasExperimentNode {
    private final RestTemplate worker = CanvasExperimentController.worker();
    private final ObjectMapper mapper = new ObjectMapper();

    @Flow(CanvasExperimentController.NODE)
    public void runNode(String canvasRunId) {
        JsonNode result = worker.postForObject(CanvasExperimentController.WORKER + "/step",
                mapper.createObjectNode().put("run_id", canvasRunId), JsonNode.class);
        if (result == null || !result.hasNonNull("node")) {
            throw new IllegalStateException("The canvas worker did not execute the event");
        }
    }
}
