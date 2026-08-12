def resolve_rule($root; $rule):
  if (($rule | type) == "object" and ($rule | has("$ref"))) then
    ($rule["$ref"] | ltrimstr("#/") | split("/")) as $path
    | $root | getpath($path)
  else
    $rule
  end;

def type_matches($value; $declared):
  if $declared == null then
    true
  elif ($declared | type) == "array" then
    any($declared[]; . == ($value | type))
  else
    ($value | type) == $declared
  end;

def validates($root; $unresolved):
  resolve_rule($root; $unresolved) as $rule
  | . as $value
  | type_matches($value; $rule.type?)
    and (
      if ($rule | has("enum")) then
        any($rule.enum[]; . == $value)
      else
        true
      end
    )
    and (
      if ($value | type) == "object" then
        all($rule.required[]?; . as $key | $value | has($key))
        and (
          if $rule.additionalProperties? == false then
            (($value | keys) - (($rule.properties? // {}) | keys) | length) == 0
          else
            true
          end
        )
        and all(
          ($rule.properties? // {}) | to_entries[];
          . as $entry
          | (($value | has($entry.key)) | not)
            or ($value[$entry.key] | validates($root; $entry.value))
        )
      else
        true
      end
    )
    and (
      if (($value | type) == "array" and ($rule | has("items"))) then
        all($value[]; validates($root; $rule.items))
      else
        true
      end
    )
    and (
      if (($value | type) == "string" and ($rule | has("minLength"))) then
        ($value | length) >= $rule.minLength
      else
        true
      end
    );

$schema[0] as $root
| validates($root; $root)
