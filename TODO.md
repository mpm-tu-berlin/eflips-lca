# Add tests

Now the eflips-model is complete, we should be able to add tests. We should take the bvg_mini database (which models one day of service), alembic-update it and use lca_params that look reasonable to add a well-covered pytest-based test suite to this.

# Add output

We should proabably make pandas a dependency and be able to create dataframes that show the value and composition of where the effects come from in a  way that allows the creation of comparative bar charts between different scenarios

# Clarify how the values should be created

Based on the deisgn document and the existing code, create a clear guide for our LCA personnel what we want the effects for. Describe unanbguously what we want, but also explain the context.

# Add CI

After having tests, we should look at the other eflips projects and take over the CI stuff that works well there. 