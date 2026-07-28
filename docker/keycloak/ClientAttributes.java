import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import java.util.regex.Pattern;

public final class ClientAttributes {
  private static final ObjectMapper JSON = new ObjectMapper();
  private static final Set<String> EXPECTED_KEYS =
      Set.of(
          "realm_client",
          "client.secret.creation.time",
          "post.logout.redirect.uris",
          "pkce.code.challenge.method");
  private static final Pattern DECIMAL = Pattern.compile("[0-9]+");

  private ClientAttributes() {}

  public static void main(String[] args) throws Exception {
    if (args.length != 1) {
      throw new IllegalArgumentException("Expected clear or verify action");
    }

    JsonNode root = JSON.readTree(System.in);
    JsonNode attributes = root.path("attributes");
    if (!attributes.isObject()) {
      throw new IllegalStateException("Missing client attributes object");
    }

    switch (args[0]) {
      case "clear" -> clear(root, attributes);
      case "verify" -> verify(attributes);
      default -> throw new IllegalArgumentException("Expected clear or verify action");
    }
  }

  private static void clear(JsonNode root, JsonNode attributes) throws Exception {
    JsonNode clientId = root.get("clientId");
    if (clientId == null || !clientId.isTextual()) {
      throw new IllegalStateException("Missing client identifier");
    }

    ObjectNode update = JSON.createObjectNode();
    update.set("clientId", clientId);
    ObjectNode clearedAttributes = update.putObject("attributes");
    Iterator<String> keys = attributes.fieldNames();
    while (keys.hasNext()) {
      String key = keys.next();
      if (EXPECTED_KEYS.contains(key)) {
        clearedAttributes.set(key, attributes.get(key));
      } else {
        clearedAttributes.putNull(key);
      }
    }
    JSON.writeValue(System.out, update);
  }

  private static void verify(JsonNode attributes) {
    Set<String> actualKeys = new HashSet<>();
    attributes.fieldNames().forEachRemaining(actualKeys::add);
    if (!actualKeys.equals(EXPECTED_KEYS)) {
      throw new IllegalStateException("Client attribute keys do not match the approved set");
    }

    expectValue(attributes, "realm_client", "false");
    expectValue(
        attributes, "post.logout.redirect.uris", "http://localhost:3000/*");
    expectValue(attributes, "pkce.code.challenge.method", "S256");

    String creationTime = attributes.path("client.secret.creation.time").asText("");
    if (!DECIMAL.matcher(creationTime).matches()) {
      throw new IllegalStateException("Client secret creation time is not numeric");
    }
  }

  private static void expectValue(
      JsonNode attributes, String key, String expectedValue) {
    if (!expectedValue.equals(attributes.path(key).asText(null))) {
      throw new IllegalStateException("Client attribute value is incorrect");
    }
  }
}
